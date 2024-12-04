from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
import copy
import os
import re

os.environ["KOREO_DEV_TOOLING"] = "true"

import yaml

import nanoid

from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument
from lsprotocol import types

from koreo import cache
from koreo.function.structure import Function
from koreo.function_test.structure import FunctionTest
from koreo.result import is_unwrapped_ok, is_not_ok
from koreo.workflow.structure import Workflow, ErrorStep

from koreo_tooling import constants
from koreo_tooling.analysis import call_arg_compare
from koreo_tooling.function_test import TestResults, run_function_tests
from koreo_tooling.indexing import (
    IndexingLoader,
    TokenModifiers,
    TokenTypes,
    _RANGE_KEY,
    _STRUCTURE_KEY,
    compute_abs_range,
    anchor_path_search,
    extract_diagnostics,
    flatten,
    range_stripper,
    to_lsp_semantics,
    generate_key_range_index,
)

KOREO_LSP_NAME = "koreo-ls"
KOREO_LSP_VERSION = "v1alpha8"

server = LanguageServer(KOREO_LSP_NAME, KOREO_LSP_VERSION)


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
async def completions(params: types.CompletionParams):
    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug, message=f"completion params: {params}"
        )
    )

    # TODO: Add awareness of the context to surface the correct completions.

    items = []

    for cache_type, cached in cache.__CACHE.items():
        for resource_key, _ in cached.items():
            items.append(
                types.CompletionItem(
                    label=resource_key,
                    label_details=types.CompletionItemLabelDetails(
                        detail=f" {cache_type}"
                    ),
                )
            )

    return types.CompletionList(is_incomplete=True, items=items)


def _input_error_formatter(actual: bool, expected: bool) -> str:
    if actual and not expected:
        return "unexpected"

    if not actual and expected:
        return "*missing*"

    return "_unknown_"


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(params: types.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(path=doc.path, line=params.position.line)
    if not resource_info:
        return None

    resource_key, resource_key_range = resource_info

    workflow_match = WORKFLOW_NAME.match(resource_key)
    if workflow_match:
        workflow_name = workflow_match.group("name")

        hover_content = [f"# {workflow_name}"]

        workflow = cache.get_resource_from_cache(
            resource_class=Workflow, cache_key=workflow_name
        )

        if not workflow:
            hover_content.append(f"Workflow {workflow_name} not in Koreo Cache")
        elif not is_unwrapped_ok(workflow):
            hover_content.append("Workflow not ready")
            hover_content.append(f"{workflow.message}")
        elif is_not_ok(workflow.steps_ready):
            hover_content.append("Workflow steps not ready")
            hover_content.append(f"{workflow.steps_ready.message}")
        else:
            hover_content.append("*Ready*")

        return types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=resource_key_range,
        )

    if resource_key.startswith("Function:"):
        function_name = resource_key.split(":")[1]

        hover_content = [f"# {function_name}"]

        function = cache.get_resource_from_cache(
            resource_class=Function, cache_key=function_name
        )

        if is_unwrapped_ok(function):
            hover_content.append("*Ready*")
        else:
            hover_content.append("Function not ready")
            hover_content.append(f"{function.message}")

        return types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=resource_key_range,
        )

    if resource_key.startswith("FunctionTest:"):
        test_name = resource_key.split(":")[1]
        result = __TEST_RESULTS[doc.path].get(test_name)
        hover_content = []
        if not result:
            hover_content.append(f"*Test has not ran*")
        else:
            if result.success:
                hover_content.append(f"# *Success*")

                if result.input_mismatches:
                    hover_content.append("## Unused Inputs")
                    hover_content.append("| Field | Issue | Severity |")
                    hover_content.append("|:-|-:|:-:|")
                    for mismatch in result.input_mismatches:
                        hover_content.append(
                            f"| `{mismatch.field}` | {_input_error_formatter(actual=mismatch.actual, expected=mismatch.expected)} | {mismatch.severity} |"
                        )
                    hover_content.append("\n")

            else:
                hover_content.append("# *Error*")
                if result.messages:
                    hover_content.append("## Failure")
                    hover_content.extend(result.messages)

                if result.input_mismatches:
                    hover_content.append("## Input Mismatches")
                    hover_content.append("| Field | Issue | Severity |")
                    hover_content.append("|:-|-:|:-:|")
                    for mismatch in result.input_mismatches:
                        hover_content.append(
                            f"| `{mismatch.field}` | {_input_error_formatter(actual=mismatch.actual, expected=mismatch.expected)} | {mismatch.severity} |"
                        )
                    hover_content.append("\n")

                if result.resource_field_errors:
                    hover_content.append("## Field Mismatches")
                    hover_content.append("| Field | Actual | Expected |")
                    hover_content.append("|:-|-:|-:|")
                    for compare in result.resource_field_errors:
                        hover_content.append(
                            f"| `{compare.field}` | {compare.actual} | {compare.expected} |"
                        )
                    hover_content.append("\n")

                if result.outcome_fields_errors:
                    hover_content.append("## Outcome Mismatches")
                    hover_content.append("| Field | Actual | Expected |")
                    hover_content.append("|:-|-:|-:|")
                    for compare in result.outcome_fields_errors:
                        hover_content.append(
                            f"| `{compare.field}` | {compare.actual} | {compare.expected} |"
                        )
                    hover_content.append("\n")

        return types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=types.Range(
                start=types.Position(line=params.position.line, character=0),
                end=types.Position(line=params.position.line + 1, character=0),
            ),
        )

    return None


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hints(params: types.InlayHintParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    test_results = __TEST_RESULTS[doc.path]
    if not test_results:
        return []

    start_line = params.range.start.line
    end_line = params.range.end.line

    visible_tests = []
    for path, maybe_resource, maybe_range in __SEMANTIC_RANGE_INDEX:
        if path != doc.path:
            continue

        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if not (start_line <= maybe_range.start.line <= end_line):
            continue

        match = FUNCTION_TEST_NAME.match(maybe_resource)
        if not match:
            continue

        visible_tests.append((match.group("name"), maybe_range))

    if not visible_tests:
        return []

    inlays = []
    for test_name, name_range in visible_tests:
        result = __TEST_RESULTS[doc.path].get(test_name)

        if not result:
            inlay = "Not Ran"
        elif result.success:
            inlay = "Success"
        else:
            inlay = "Error"

        char = len(doc.lines[name_range.end.line])

        inlays.append(
            types.InlayHint(
                label=inlay,
                kind=types.InlayHintKind.Type,
                padding_left=True,
                padding_right=True,
                position=types.Position(line=name_range.end.line, character=char),
            )
        )

    return inlays


@server.feature(types.TEXT_DOCUMENT_CODE_LENS)
def code_lens(params: types.CodeLensParams):
    """Return a list of code lens to insert into the given document.

    This method will read the whole document and identify each sum in the document and
    tell the language client to insert a code lens at each location.
    """
    return None
    doc = server.workspace.get_text_document(params.text_document.uri)

    test_results = __TEST_RESULTS[doc.path]
    if not test_results:
        return []

    doc_function_tests = {
        resource_index_key: [
            __RANGE_INDEX[doc.path][_range_key(resource_range)]
            for resource_range in __RESOURCE_RANGE_INDEX[resource_index_key][doc.path]
        ]
        for resource_index_key in __PATH_RESOURCE_INDEX[doc.path]
        if resource_index_key.startswith("FunctionTest:")
    }

    lens = []
    for test_name, test_result in test_results.items():
        if test_result.success:
            continue

        test_key = f"FunctionTest:{test_name}"

        function_test_specs = doc_function_tests.get(test_key)
        if not function_test_specs:
            continue

        function_test_spec = function_test_specs.pop()
        if not function_test_spec:
            continue

        if test_result.input_mismatches and False:
            inputs = function_test_spec.get("inputs")
            if not inputs:
                continue

            inputs_range = inputs.get(_RANGE_KEY)

            code_lens = types.CodeLens(
                range=inputs_range,
                command=types.Command(
                    title="Generate inputs",
                    command="codeLens.completeInputs",
                    arguments=[
                        {
                            "path": doc.path,
                            "uri": params.text_document.uri,
                            "version": doc.version,
                            "range": _range_key(inputs_range),
                            "missing_inputs": list(test_result.missing_inputs),
                            "test_name": test_name,
                        }
                    ],
                ),
            )
            lens.append(code_lens)
            continue

        ref_range = function_test_spec.get(_RANGE_KEY)

        range_start_line = ref_range.start.line
        range_end_line = ref_range.end.line

        expected_resource_line = None
        expected_resource_char = None

        wrong_lines = []
        for line_offset in range(range_end_line - range_start_line):
            line_data = doc.lines[range_start_line + line_offset]
            line_data_stripped = line_data.lstrip()

            if line_data_stripped.startswith("expectedResource"):
                expected_resource_line = range_start_line + line_offset
                expected_resource_char = len(line_data) - len(line_data_stripped)
                break
            wrong_lines.append(line_data)

        if expected_resource_line is None:
            continue

        range_ = types.Range(
            start=types.Position(
                line=expected_resource_line, character=expected_resource_char + 16
            ),
            end=types.Position(
                line=expected_resource_line, character=expected_resource_char + 30
            ),
        )

        code_lens = types.CodeLens(
            range=range_,
            command=types.Command(
                title="Auto-complete resource def",
                command="codeLens.fillexpectedResource",
                arguments=[
                    {
                        "path": doc.path,
                        "uri": params.text_document.uri,
                        "version": doc.version,
                        "line": expected_resource_line,
                        "indent": expected_resource_char,
                        "test_name": test_name,
                    }
                ],
            ),
        )
        lens.append(code_lens)

    return lens


@server.command("codeLens.completeInputs")
def code_lens_inputs_action(args):
    if not args:
        return

    edit_args = args[0]

    doc_uri = edit_args["uri"]
    inputs_range_key = edit_args["range"]
    missing_inputs = edit_args["missing_inputs"]

    raise Exception(f"{inputs_range_key}: {missing_inputs}")

    doc = server.workspace.get_text_document(doc_uri)

    start_line, end_line = _range_key_to_lines(inputs_range_key)

    start_line = expected_resource_line + 1
    end_line = start_line
    end_char = 0
    indent = expected_resource_indent + 2

    while end_line < len(doc.lines):
        line_data = doc.lines[end_line]
        first_char = len(line_data) - len(line_data.lstrip())

        if first_char <= expected_resource_indent:
            break

        # In case they're using other than 2 indent
        indent = min(indent, first_char)

        end_line += 1

    end_line -= 1
    end_char = len(doc.lines[end_line])

    test_result = __TEST_RESULTS[edit_args["path"]][edit_args["test_name"]]

    indent = " " * indent

    actual_resource = "\n".join(
        f"{indent}{line}"
        for line in yaml.dump(test_result.actual_resource).splitlines()
    )

    edit = types.TextDocumentEdit(
        text_document=types.OptionalVersionedTextDocumentIdentifier(
            uri=doc_uri,
            version=edit_args["version"],
        ),
        edits=[
            types.TextEdit(
                new_text=actual_resource,
                range=types.Range(
                    start=types.Position(line=start_line, character=0),
                    end=types.Position(line=end_line, character=end_char),
                ),
            )
        ],
    )

    # Apply the edit.
    server.workspace_apply_edit(
        types.ApplyWorkspaceEditParams(
            edit=types.WorkspaceEdit(document_changes=[edit]),
        ),
    )


@server.command("codeLens.fillexpectedResource")
def code_lens_action(args):
    if not args:
        return

    edit_args = args[0]

    doc_uri = edit_args["uri"]
    expected_resource_line = edit_args["line"]
    expected_resource_indent = edit_args["indent"]

    doc = server.workspace.get_text_document(doc_uri)

    start_line = expected_resource_line + 1
    end_line = start_line
    end_char = 0
    indent = expected_resource_indent + 2

    while end_line < len(doc.lines):
        line_data = doc.lines[end_line]
        first_char = len(line_data) - len(line_data.lstrip())

        if first_char <= expected_resource_indent:
            break

        # In case they're using other than 2 indent
        indent = min(indent, first_char)

        end_line += 1

    end_line -= 1
    end_char = len(doc.lines[end_line])

    test_result = __TEST_RESULTS[edit_args["path"]][edit_args["test_name"]]

    indent = " " * indent

    actual_resource = "\n".join(
        f"{indent}{line}"
        for line in yaml.dump(test_result.actual_resource).splitlines()
    )

    edit = types.TextDocumentEdit(
        text_document=types.OptionalVersionedTextDocumentIdentifier(
            uri=doc_uri,
            version=edit_args["version"],
        ),
        edits=[
            types.TextEdit(
                new_text=actual_resource,
                range=types.Range(
                    start=types.Position(line=start_line, character=0),
                    end=types.Position(line=end_line, character=end_char),
                ),
            )
        ],
    )

    # Apply the edit.
    server.workspace_apply_edit(
        types.ApplyWorkspaceEditParams(
            edit=types.WorkspaceEdit(document_changes=[edit]),
        ),
    )


@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
async def change_workspace_config(params):

    suffixes = ("yaml", "yml", "koreo")

    for folder_key in server.workspace.folders:
        path = Path(server.workspace.get_text_document(folder_key).path)

        for suffix in suffixes:
            for match in path.rglob(f"*.{suffix}"):

                doc = server.workspace.get_text_document(f"{match}")
                await _handle_file(doc=doc)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def open_processor(params):

    doc = server.workspace.get_text_document(params.text_document.uri)
    await _handle_file(doc=doc)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def change_processor(params):

    doc = server.workspace.get_text_document(params.text_document.uri)
    await _handle_file(doc=doc)


def _lookup_current_line_info(path: str, line: int) -> tuple[str, types.Range] | None:
    for maybe_path, maybe_key, maybe_range in __SEMANTIC_RANGE_INDEX:
        if maybe_path != path:
            continue

        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if maybe_range.start.line == line:
            return (maybe_key, maybe_range)

    return None


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
async def goto_definitiion(params: types.DefinitionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(path=doc.path, line=params.position.line)
    if not resource_info:
        return []

    resource_key, _ = resource_info

    resource_key_root = resource_key.rsplit(":", 1)[0]
    search_key = f"{resource_key_root}:def"

    definitions = []
    for path, maybe_key, maybe_range in __SEMANTIC_RANGE_INDEX:
        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if maybe_key != search_key:
            continue

        definitions.append(types.Location(uri=path, range=maybe_range))

    return definitions


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
async def goto_reference(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(path=doc.path, line=params.position.line)
    if not resource_info:
        return []

    resource_key, _ = resource_info

    resource_key_root = resource_key.rsplit(":", 1)[0]
    reference_key = f"{resource_key_root}:ref"
    definition_key = f"{resource_key_root}:def"

    references: list[types.Location] = []
    definitions: list[types.Location] = []
    for path, maybe_key, maybe_range in __SEMANTIC_RANGE_INDEX:
        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if maybe_key == reference_key:
            references.append(types.Location(uri=path, range=maybe_range))

        if maybe_key == definition_key:
            definitions.append(types.Location(uri=path, range=maybe_range))

    return references + definitions


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    types.SemanticTokensLegend(token_types=TokenTypes, token_modifiers=TokenModifiers),
)
async def semantic_tokens_full(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc.path in __SEMANTIC_TOKEN_INDEX:
        await _handle_file(doc=doc)

    tokens = __SEMANTIC_TOKEN_INDEX[doc.path]
    return types.SemanticTokens(data=tokens)


PATH_GUARD: dict[str, int | None] = {}


async def _handle_file(doc: TextDocument):
    guard_value = PATH_GUARD.get(doc.path)
    if doc.path in PATH_GUARD and guard_value and guard_value >= (doc.version or -1):
        return

    PATH_GUARD[doc.path] = doc.version if doc.version is not None else -1

    _reset_file_state(doc.path)

    try:
        if await _process_file(doc=doc):
            return
    except Exception as err:
        server.window_log_message(
            params=types.LogMessageParams(
                type=types.MessageType.Error,
                message=f"Error parsing file ({doc.path}): {err}",
            )
        )
        return

    _process_workflows(path=doc.path)

    test_diagnostics = await _run_function_test(doc=doc)

    if PATH_GUARD[doc.path] != (doc.version if doc.version is not None else -1):
        return

    if test_diagnostics:
        __DIAGNOSTICS[doc.path].extend(test_diagnostics)

    duplicate_diagnostics = _check_for_duplicate_resources(path=doc.path)
    if duplicate_diagnostics:
        __DIAGNOSTICS[doc.path].extend(duplicate_diagnostics)

    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=doc.uri, version=doc.version, diagnostics=__DIAGNOSTICS[doc.path]
        )
    )


async def _run_function_test(doc: TextDocument):
    if PATH_GUARD[doc.path] != (doc.version if doc.version is not None else -1):
        return []

    test_range_map = {}
    tests = set[str]()
    functions = set[str]()
    for resource_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if resource_path != doc.path:
            continue

        if match := FUNCTION_TEST_NAME.match(resource_key):
            test_name = match.group("name")
            tests.add(test_name)
            test_range_map[test_name] = resource_range

        elif match := FUNCTION_NAME.match(resource_key):
            functions.add(match.group("name"))

    test_results = await run_function_tests(
        server=server,
        tests_to_run=tests,
        functions_to_test=functions,
    )

    if not test_results:
        return []

    if PATH_GUARD[doc.path] != (doc.version if doc.version is not None else -1):
        return []

    __TEST_RESULTS[doc.path] = test_results

    test_diagnostics = []
    for test_key, result in test_results.items():
        if result.success:
            continue

        # TODO: Add support for reporting within Functions
        if test_key not in tests:
            continue

        cached_resource = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=test_key
        )
        if not (
            cached_resource and cached_resource.resource and cached_resource.system_data
        ):
            continue

        anchor = cached_resource.system_data.get("anchor")
        if not anchor:
            continue

        if result.messages:
            test_diagnostics.append(
                types.Diagnostic(
                    message=f"Failures: {'; '.join(result.messages)}",
                    severity=types.DiagnosticSeverity.Error,
                    range=test_range_map[test_key],
                )
            )

        test_spec_block = _block_range_extract(
            path_key="spec",
            search_nodes=anchor.children,
            doc_path=doc.path,
            anchor=anchor,
        )
        if not test_spec_block:
            continue

        if result.input_mismatches:
            inputs_block = _block_range_extract(
                path_key="inputs",
                search_nodes=test_spec_block.children,
                doc_path=doc.path,
                anchor=anchor,
            )
            if not inputs_block:
                test_diagnostics.append(
                    types.Diagnostic(
                        message="Input expected, but none provided.",
                        severity=types.DiagnosticSeverity.Warning,
                        range=compute_abs_range(test_spec_block, anchor),
                    )
                )
            else:
                for mismatch in result.input_mismatches:
                    if not mismatch.expected and mismatch.actual:
                        input_block = _block_range_extract(
                            path_key=mismatch.field,
                            search_nodes=inputs_block.children,
                            doc_path=doc.path,
                            anchor=anchor,
                        )
                        if not input_block:
                            continue

                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Input ('{mismatch.field}') not expected.",
                                severity=types.DiagnosticSeverity.Warning,
                                range=compute_abs_range(input_block, anchor),
                            )
                        )

                    elif mismatch.expected and not mismatch.actual:
                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Missing input ('{mismatch.field}').",
                                severity=types.DiagnosticSeverity.Error,
                                range=compute_abs_range(inputs_block, anchor),
                            )
                        )

        if result.resource_field_errors:
            resource_block = _block_range_extract(
                path_key="expectedResource",
                search_nodes=test_spec_block.children,
                doc_path=doc.path,
                anchor=anchor,
            )
            if not resource_block:
                test_diagnostics.append(
                    types.Diagnostic(
                        message="Resource unexpectedly modified.",
                        severity=types.DiagnosticSeverity.Error,
                        range=compute_abs_range(test_spec_block, anchor),
                    )
                )
            else:
                for mismatch in result.resource_field_errors:
                    mismatch_block = _block_range_extract(
                        path_key=mismatch.field,
                        search_nodes=resource_block.children,
                        doc_path=doc.path,
                        anchor=anchor,
                    )
                    if not mismatch_block:
                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Missing value for '{mismatch.field}'",
                                severity=types.DiagnosticSeverity.Error,
                                range=compute_abs_range(resource_block, anchor),
                            )
                        )
                    else:
                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Actual: '{mismatch.actual}'",
                                severity=types.DiagnosticSeverity.Error,
                                range=compute_abs_range(mismatch_block, anchor),
                            )
                        )

        if result.outcome_fields_errors:
            outcome_block = _block_range_extract(
                path_key="expectedOkValue",
                search_nodes=test_spec_block.children,
                doc_path=doc.path,
                anchor=anchor,
            )
            if not outcome_block:
                test_diagnostics.append(
                    types.Diagnostic(
                        message="Outcome unexpectedly reached.",
                        severity=types.DiagnosticSeverity.Error,
                        range=compute_abs_range(test_spec_block, anchor),
                    )
                )
            else:
                for mismatch in result.outcome_fields_errors:
                    mismatch_block = _block_range_extract(
                        path_key=mismatch.field,
                        search_nodes=outcome_block.children,
                        doc_path=doc.path,
                        anchor=anchor,
                    )
                    if not mismatch_block:
                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Missing value for '{mismatch.field}'",
                                severity=types.DiagnosticSeverity.Error,
                                range=compute_abs_range(outcome_block, anchor),
                            )
                        )
                    else:
                        test_diagnostics.append(
                            types.Diagnostic(
                                message=f"Actual: '{mismatch.actual}'",
                                severity=types.DiagnosticSeverity.Error,
                                range=compute_abs_range(mismatch_block, anchor),
                            )
                        )

    return test_diagnostics


__DIAGNOSTICS = defaultdict[str, list[types.Diagnostic]](list[types.Diagnostic])
__TEST_RESULTS = defaultdict[str, dict[str, TestResults]](defaultdict[str, TestResults])
__SEMANTIC_TOKEN_INDEX = defaultdict[str, list[int]](list)
__SEMANTIC_RANGE_INDEX: list[tuple[str, str, types.Range]] = []


def _range_key(resource_range: types.Range):
    return f"{resource_range.start.line}.{resource_range.start.line}:{resource_range.end.line}.{resource_range.end.line}"


def _range_key_to_lines(key: str) -> tuple[int, int]:
    start, end = key.split(":")
    start_line = int(start.split(".")[0])
    end_line = int(end.split(".")[0])
    return (start_line, end_line)


def _reset_file_state(path_key: str):
    global __SEMANTIC_RANGE_INDEX

    __SEMANTIC_RANGE_INDEX = [
        (path, node_key, node_range)
        for path, node_key, node_range in __SEMANTIC_RANGE_INDEX
        if path != path_key
    ]
    __SEMANTIC_TOKEN_INDEX[path_key] = []

    __DIAGNOSTICS[path_key] = []
    __TEST_RESULTS[path_key] = {}


def _load_all_yamls(stream, Loader, doc):
    """
    Parse all YAML documents in a stream
    and produce corresponding Python objects.
    """
    loader = Loader(stream, doc=doc)
    try:
        while loader.check_data():
            yield loader.get_data()
    finally:
        loader.dispose()


async def _process_file(
    doc: TextDocument,
):
    path = doc.path


    yaml_blocks = _load_all_yamls(doc.source, Loader=IndexingLoader, doc=doc)
    for yaml_block in yaml_blocks:
        if PATH_GUARD[doc.path] != (doc.version if doc.version is not None else -1):
            return True

        try:
            api_version = yaml_block.get("apiVersion")
            kind = yaml_block.get("kind")
        except:
            server.window_log_message(
                params=types.LogMessageParams(
                    type=types.MessageType.Info,
                    message="Skipping empty block",
                )
            )
            continue

        semantic_anchor = yaml_block.get(_STRUCTURE_KEY)

        block_ranges = [
            (path, node_key, node_range)
            for node_key, node_range in generate_key_range_index(semantic_anchor)
        ]


        __SEMANTIC_RANGE_INDEX.extend(block_ranges)

        flattened = flatten(semantic_anchor)
        tokens = to_lsp_semantics(flattened)
        __SEMANTIC_TOKEN_INDEX[path].extend(tokens)

        semantic_diagnostics = extract_diagnostics(flattened)
        if semantic_diagnostics:
            for node in semantic_diagnostics:
                __DIAGNOSTICS[path].append(
                    types.Diagnostic(
                        message=node.diagnostic.message,
                        severity=types.DiagnosticSeverity.Error,  # TODO: Map internal to LSP
                        range=types.Range(
                            start=types.Position(
                                line=semantic_anchor.abs_position.line
                                + node.anchor_rel.line,
                                character=node.anchor_rel.offset,
                            ),
                            end=types.Position(
                                line=semantic_anchor.abs_position.line
                                + node.anchor_rel.line,
                                character=node.anchor_rel.offset + node.length,
                            ),
                        ),
                    )
                )

        resource_range = yaml_block.get(_RANGE_KEY)

        if api_version not in {
            constants.API_VERSION,
            constants.CRD_API_VERSION,
        }:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"'{kind}.{api_version}' is not a Koreo Resource.",
                    severity=types.DiagnosticSeverity.Information,
                    range=resource_range,
                )
            )
            continue

        if kind not in constants.PREPARE_MAP and kind != constants.CRD_KIND:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"'{kind}' is not a supported Koreo Resource.",
                    severity=types.DiagnosticSeverity.Information,
                    range=resource_range,
                )
            )
            continue

        # continue
        resource_class, preparer = constants.PREPARE_MAP[kind]
        metadata = yaml_block.get("metadata", {})
        metadata["resourceVersion"] = nanoid.generate(size=10)

        raw_spec = yaml_block.get("spec", {})

        cached_system_data = {
            "path": path,
            "anchor": semantic_anchor,
        }

        try:
            range_stripped = range_stripper(copy.deepcopy(raw_spec))
            await cache.prepare_and_cache(
                resource_class=resource_class,
                preparer=preparer,
                metadata=metadata,
                spec=range_stripped,
                _system_data=cached_system_data,
            )
        except Exception as err:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"FAILED TO Extract ('{kind}.{api_version}') from {metadata.get('name')} ({err}).",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )

            raise

    return False


WORKFLOW_NAME = re.compile("Workflow:(?P<name>[^:]*)?:def")
FUNCTION_NAME = re.compile("Function:(?P<name>.*)?:def")
FUNCTION_TEST_NAME = re.compile("FunctionTest:(?P<name>.*)?:def")
RESOURCE_DEF = re.compile("([A-Z][a-zA-Z0-9.]*):(.*):def")


def _check_for_duplicate_resources(path: str):
    counts: defaultdict[str, tuple[int, bool, list[tuple]]] = defaultdict(
        lambda: (0, False, [])
    )

    for resource_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if not RESOURCE_DEF.match(resource_key):
            continue

        count, seen_in_path, locations = counts[resource_key]
        locations.append((resource_path, resource_range))
        counts[resource_key] = (
            count + 1,
            seen_in_path or resource_path == path,
            locations,
        )

    duplicate_diagnostics: list[types.Diagnostic] = []

    for resource_key, (count, seen_in_path, locations) in counts.items():
        if count <= 1 or not seen_in_path:
            continue

        for resource_path, resource_range in locations:
            if resource_path != path:
                continue

            duplicate_diagnostics.append(
                types.Diagnostic(
                    message=f"Mulitiple instances of {resource_key}.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )

    return duplicate_diagnostics


def _process_workflows(path: str):
    for maybe_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if maybe_path != path:
            continue

        match = WORKFLOW_NAME.match(resource_key)
        if not match:
            continue

        koreo_cache_key = match.group("name")

        cached_resource = cache.get_resource_system_data_from_cache(
            resource_class=Workflow, cache_key=koreo_cache_key
        )

        if not cached_resource or not cached_resource.resource:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Workflow not yet prepared ({koreo_cache_key}) or not in Koreo cache.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )
            continue

        _process_workflow(
            path=path,
            resource_range=resource_range,
            workflow_name=koreo_cache_key,
            workflow=cached_resource.resource,
            raw_spec=cached_resource.spec,
            koreo_metadata=cached_resource.system_data,
        )


def _process_workflow(
    path: str,
    resource_range: types.Range,
    workflow_name: str,
    workflow: Workflow,
    raw_spec: dict,
    koreo_metadata: dict | None,
) -> bool:
    has_step_error = False

    if not koreo_metadata:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow ('{workflow_name}') missing in Koreo Cache (this _should_ be impossible).",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )
        return True

    semantic_path = koreo_metadata.get("path", "")
    if semantic_path != path:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=(
                    f"Duplicate Workflow ('{workflow_name}') detected in "
                    f"('{semantic_path}'), skipping further analysis."
                ),
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )
        return True

    semantic_anchor = koreo_metadata.get("anchor")
    if not semantic_anchor:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Unknown error processing Workflow ('{workflow_name}'), semantic analysis data missing from Koreo cache.",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )
        return True

    spec_block = _block_range_extract(
        path_key="spec",
        search_nodes=semantic_anchor.children,
        doc_path=path,
        anchor=semantic_anchor,
    )
    if not spec_block:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message="Missing `spec`",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )
        return True

    steps_block = _block_range_extract(
        path_key="steps",
        search_nodes=spec_block.children,
        doc_path=path,
        anchor=semantic_anchor,
    )
    if not steps_block:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message="Missing `spec.steps`",
                severity=types.DiagnosticSeverity.Error,
                range=compute_abs_range(spec_block, semantic_anchor),
            )
        )
        return True

    if not is_unwrapped_ok(workflow.steps_ready):
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow is not ready ({workflow.steps_ready.message}).",
                severity=types.DiagnosticSeverity.Warning,
                range=resource_range,
            )
        )

    step_specs = {
        step_spec.get("label"): step_spec for step_spec in raw_spec.get("steps", [])
    }

    if not step_specs and workflow.steps:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow steps are malformed.",
                severity=types.DiagnosticSeverity.Warning,
                range=resource_range,
            )
        )
        return True

    for step in workflow.steps:
        step_block = _block_range_extract(
            path_key=f"Step:{step.label}",
            search_nodes=steps_block.children,
            doc_path=path,
            anchor=semantic_anchor,
        )
        if not step_block:
            continue

        step_spec = step_specs.get(step.label)

        step_error = _process_workflow_step(
            path, step, step_block, step_spec, semantic_anchor
        )

        has_step_error = has_step_error or step_error

    if has_step_error:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow steps are not ready.",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )

    return has_step_error


def _process_workflow_step(path, step, step_semantic_block, step_spec, semantic_anchor):
    has_error = False

    if isinstance(step, ErrorStep):
        label_block = _key_value_range_extract(
            path_key="label",
            search_nodes=step_semantic_block.children,
            doc_path=path,
            anchor=semantic_anchor,
        )
        if not label_block:
            return True

        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Step ('{step.label}') not ready {step.outcome.message}.",
                severity=types.DiagnosticSeverity.Warning,
                range=compute_abs_range(label_block, semantic_anchor),
            )
        )
        return True

    # These are just the "top level" direct inputs. No consideration to
    # internal structure.
    first_tier_inputs = set(
        constants.INPUT_NAME_PATTERN.match(key).group(1)
        for key in step.logic.dynamic_input_keys
        if key.startswith("inputs")
    )

    raw_inputs = step_spec.get("inputs", {})

    inputs_block = _block_range_extract(
        path_key="inputs",
        search_nodes=step_semantic_block.children,
        doc_path=path,
        anchor=semantic_anchor,
    )

    inputs = call_arg_compare(step.provided_input_keys, first_tier_inputs)
    for argument, (provided, expected) in inputs.items():
        if not expected and provided:
            has_error = True

            if not inputs_block:
                continue
            input_block = _block_range_extract(
                path_key=argument,
                search_nodes=inputs_block.children,
                doc_path=path,
                anchor=semantic_anchor,
            )
            if not input_block:
                continue

            raw_arg = raw_inputs.get(argument)
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Input ('{argument}') not expected. {raw_arg}.",
                    severity=types.DiagnosticSeverity.Warning,
                    range=compute_abs_range(input_block, semantic_anchor),
                )
            )

        elif expected and not provided:
            has_error = True

            if not inputs_block:
                continue

            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Missing input ('{argument}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(inputs_block, semantic_anchor),
                )
            )

    return has_error


def _block_range_extract(path_key: str, search_nodes: Sequence, doc_path: str, anchor):
    matches = anchor_path_search([path_key], _search_nodes=search_nodes)

    if not matches:
        return None

    match, *extras = matches

    if extras:
        for match in matches:
            __DIAGNOSTICS[doc_path].append(
                types.Diagnostic(
                    message=f"Multiple instances of ('{path_key}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(match, anchor),
                )
            )

        return None

    return match


def _key_value_range_extract(
    path_key: str, search_nodes: Sequence, doc_path: str, anchor
):
    yaml_key = _block_range_extract(
        path_key=path_key, search_nodes=search_nodes, doc_path=doc_path, anchor=anchor
    )
    if not yaml_key:
        return None

    if not yaml_key.children:
        __DIAGNOSTICS[doc_path].append(
            types.Diagnostic(
                message=f"Missing value for ('{path_key}').",
                severity=types.DiagnosticSeverity.Warning,
                range=compute_abs_range(yaml_key, anchor),
            )
        )
        return None

    value, *extras = yaml_key.children

    if extras:
        for child in yaml_key.children:
            __DIAGNOSTICS[doc_path].append(
                types.Diagnostic(
                    message=f"Multiple instances of ('{path_key}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(child, anchor),
                )
            )

        return None

    return value


if __name__ == "__main__":
    server.start_io()
