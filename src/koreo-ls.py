from asyncio import Semaphore
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple, Sequence
import copy
import os

os.environ["KOREO_DEV_TOOLING"] = "true"

import yaml


from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument
from lsprotocol import types

from koreo import cache
from koreo.function.structure import Function
from koreo.function_test.structure import FunctionTest
from koreo.workflow.structure import Workflow

from koreo_tooling import constants
from koreo_tooling.function_test import TestResults
from koreo_tooling.indexing import (
    TokenModifiers,
    TokenTypes,
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    compute_abs_range,
    compute_abs_position,
)

from koreo_tooling.indexing.semantics import generate_local_range_index

from koreo_tooling.langserver.fileprocessor import process_file
from koreo_tooling.langserver.workflow import process_workflows
from koreo_tooling.langserver.function_test import run_function_tests
from koreo_tooling.langserver.rangers import block_range_extract
from koreo_tooling.langserver.hover import handle_hover

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


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(params: types.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(path=doc.path, line=params.position.line)
    if not resource_info.index_match:
        return None

    hover_result = handle_hover(
        resource_key=resource_info.index_match.key,
        resource_key_range=resource_info.index_match.range,
        local_resource=resource_info.local_match,
        test_results=__TEST_RESULTS[doc.path],
    )

    if not hover_result:
        return None

    if hover_result.logs:
        for log in hover_result.logs:
            server.window_log_message(params=log)

    return hover_result.hover


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

        match = constants.FUNCTION_TEST_NAME.match(maybe_resource)
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
    doc = server.workspace.get_text_document(params.text_document.uri)

    test_results = __TEST_RESULTS[doc.path]
    if not test_results:
        return []

    lens = []
    for test_name, test_result in test_results.items():
        if test_result.success:
            continue

        cached = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=test_name
        )

        if not (cached and cached.resource and cached.system_data):
            continue

        if cached.system_data.get("path") != doc.path:
            continue

        test_anchor = cached.system_data.get("anchor")
        if not test_anchor:
            continue

        if test_result.input_mismatches:
            if not any(
                mismatch.field.startswith("inputs.")
                for mismatch in test_result.input_mismatches
            ):
                continue

            inputs_block = block_range_extract(
                search_key="inputs",
                search_nodes=test_anchor.children,
                anchor=test_anchor,
            )
            match inputs_block:
                case None:
                    continue
                case list(_):
                    continue

            code_lens = types.CodeLens(
                range=compute_abs_range(inputs_block, test_anchor),
                command=types.Command(
                    title="Autocorrect Inputs",
                    command="codeLens.completeInputs",
                    arguments=[
                        {
                            "uri": params.text_document.uri,
                            "version": doc.version,
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
    doc_version = edit_args["version"]
    test_name = edit_args["test_name"]

    doc = server.workspace.get_text_document(doc_uri)
    if doc.version != doc_version:
        return

    doc_path = doc.path

    test_result = __TEST_RESULTS[doc_path][test_name]
    if not test_result.input_mismatches:
        return

    cached = cache.get_resource_system_data_from_cache(
        resource_class=FunctionTest, cache_key=test_name
    )
    if not (cached and cached.resource and cached.system_data):
        return

    test_anchor = cached.system_data.get("anchor")
    if not test_anchor:
        return

    inputs_block = block_range_extract(
        search_key="inputs",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match inputs_block:
        case None:
            return
        case list(_):
            return

    inputs_value_block = block_range_extract(
        search_key="InputValues",
        search_nodes=inputs_block.children,
        anchor=test_anchor,
    )
    match inputs_value_block:
        case None | list(_):
            return

    spec_inputs = copy.deepcopy(cached.spec.get("inputs"))


    if not spec_inputs:
        spec_inputs = {
            mismatch.field.split(".", 1)[-1]: "TODO"
            for mismatch in test_result.input_mismatches
            if mismatch.expected
        }
    else:
        for mismatch in test_result.input_mismatches:
            group, field_name = mismatch.field.split(".", 1)
            if group != "inputs":
                continue

            if mismatch.actual and not mismatch.expected:
                del spec_inputs[field_name]

            if not mismatch.actual and mismatch.expected:
                spec_inputs[field_name] = "TODO"

    formated_inputs = f"\n{"\n".join(
        f"{(inputs_block.anchor_rel.character + 2) * ' '}{line}"
        for line in yaml.dump(spec_inputs).splitlines()
    )}\n\n"

    match inputs_value_block:
        case SemanticAnchor(abs_position=abs_position):
            end_pos = abs_position

        case SemanticBlock(anchor_rel=anchor_rel):
            end_pos = types.Position(
                line=anchor_rel.end.line + test_anchor.abs_position.line, character=0
            )

        case SemanticNode(anchor_rel=anchor_rel, length=length):
            end_pos = compute_abs_position(
                anchor_rel, test_anchor.abs_position, length=length
            )

    edit = types.TextDocumentEdit(
        text_document=types.OptionalVersionedTextDocumentIdentifier(
            uri=doc_uri,
            version=edit_args["version"],
        ),
        edits=[
            types.TextEdit(
                new_text=formated_inputs,
                range=types.Range(
                    start=compute_abs_position(
                        inputs_block.anchor_rel,
                        test_anchor.abs_position,
                        length=inputs_block.length + 1,
                    ),
                    end=end_pos,
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


class ResourceMatch(NamedTuple):
    key: str
    range: types.Range


class CurrentLineInfo(NamedTuple):
    index_match: ResourceMatch | None = None
    local_match: ResourceMatch | None = None


def _lookup_current_line_info(path: str, line: int) -> CurrentLineInfo:
    possible_match: tuple[str, types.Range] | None = None
    for maybe_path, maybe_key, maybe_range in __SEMANTIC_RANGE_INDEX:
        if maybe_path != path:
            continue

        if not isinstance(maybe_range, types.Range):
            continue

        if maybe_range.start.line == line:
            return CurrentLineInfo(
                index_match=ResourceMatch(key=maybe_key, range=maybe_range)
            )

        if maybe_range.start.line <= line <= maybe_range.end.line:
            possible_match = ResourceMatch(key=maybe_key, range=maybe_range)

    if not possible_match:
        return CurrentLineInfo()

    if match := constants.WORKFLOW_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=Workflow, cache_key=match.group("name")
        )
    elif match := constants.FUNCTION_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=Function, cache_key=match.group("name")
        )
    elif match := constants.FUNCTION_TEST_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=match.group("name")
        )
    else:
        return CurrentLineInfo()

    if not cached or not cached.system_data or "anchor" not in cached.system_data:
        return CurrentLineInfo()

    anchor: SemanticAnchor = cached.system_data.get("anchor")
    anchor_index = generate_local_range_index(nodes=anchor.children, anchor=anchor)

    for maybe_key, maybe_range in anchor_index:
        if not isinstance(maybe_range, types.Range):
            continue

        if maybe_range.start.line == line:
            return CurrentLineInfo(
                index_match=possible_match,
                local_match=ResourceMatch(key=maybe_key, range=maybe_range),
            )

    return CurrentLineInfo()


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
async def goto_definitiion(params: types.DefinitionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(path=doc.path, line=params.position.line)
    if not resource_info.index_match:
        return []

    resource_key_root = resource_info.index_match.key.rsplit(":", 1)[0]
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
    if not resource_info.index_match:
        return []

    resource_key_root = resource_info.index_match.key.rsplit(":", 1)[0]
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


__PATH_GUARD_SEM: dict[str, Semaphore] = {}
__PATH_GUARD: dict[str, int] = {}


async def _handle_file(doc: TextDocument):
    doc_version = doc.version if doc.version else -1

    if doc.path not in __PATH_GUARD_SEM:
        __PATH_GUARD_SEM[doc.path] = Semaphore(1)

    async with __PATH_GUARD_SEM[doc.path]:
        if doc.path in __PATH_GUARD and doc_version <= __PATH_GUARD[doc.path]:
            return

        __PATH_GUARD[doc.path] = doc_version

        await _guarded_handle_file(doc)


async def _guarded_handle_file(doc: TextDocument):
    _reset_file_state(doc.path)

    diagnostics = []

    try:
        process_diagnostics = await _process_file(doc=doc)
        if process_diagnostics:
            diagnostics.extend(process_diagnostics)
    except Exception as err:
        return

    diagnostics.extend(_process_workflows(path=doc.path))
    diagnostics.extend(await _run_function_test(doc=doc))
    diagnostics.extend(_check_for_duplicate_resources(path=doc.path))

    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=doc.uri, version=doc.version, diagnostics=diagnostics
        )
    )


def _process_workflows(path: str) -> list[types.Diagnostic]:
    workflows = []
    for maybe_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if maybe_path != path:
            continue

        match = constants.WORKFLOW_NAME.match(resource_key)
        if not match:
            continue

        workflows.append((match.group("name"), resource_range))

    return process_workflows(path=path, workflows=workflows)


async def _run_function_test(doc: TextDocument) -> list[types.Diagnostic]:
    test_range_map = {}
    tests_to_run = set[str]()
    functions_to_test = set[str]()
    for resource_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if resource_path != doc.path:
            continue

        if match := constants.FUNCTION_TEST_NAME.match(resource_key):
            test_name = match.group("name")
            tests_to_run.add(test_name)
            test_range_map[test_name] = resource_range

        elif match := constants.FUNCTION_NAME.match(resource_key):
            functions_to_test.add(match.group("name"))

    if not (tests_to_run or functions_to_test):
        return []

    test_results = await run_function_tests(
        tests_to_run=tests_to_run,
        functions_to_test=functions_to_test,
        test_range_map=test_range_map,
    )

    if test_results.results:
        __TEST_RESULTS[doc.path] = test_results.results

    if test_results.logs:
        for log in test_results.logs:
            server.window_log_message(params=log)

    if test_results.diagnostics:
        return test_results.diagnostics

    return []


__TEST_RESULTS = defaultdict[str, dict[str, TestResults]](dict)
__SEMANTIC_TOKEN_INDEX: dict[str, Sequence[int]] = {}
__SEMANTIC_RANGE_INDEX: list[tuple[str, str, types.Range]] = []


def _reset_file_state(path_key: str):
    global __SEMANTIC_RANGE_INDEX

    __SEMANTIC_RANGE_INDEX = [
        (path, node_key, node_range)
        for path, node_key, node_range in __SEMANTIC_RANGE_INDEX
        if path != path_key
    ]

    if path_key in __SEMANTIC_TOKEN_INDEX:
        del __SEMANTIC_TOKEN_INDEX[path_key]

    if path_key in __TEST_RESULTS:
        del __TEST_RESULTS[path_key]


async def _process_file(
    doc: TextDocument,
):
    results = await process_file(doc=doc)

    if not results:
        return

    if results.semantic_range_index:
        __SEMANTIC_RANGE_INDEX.extend(results.semantic_range_index)

    if results.semantic_tokens:
        __SEMANTIC_TOKEN_INDEX[doc.path] = results.semantic_tokens

    if results.logs:
        for log in results.logs:
            server.window_log_message(params=log)

        return results.diagnostics

    if results.diagnostics:
        return results.diagnostics


def _check_for_duplicate_resources(path: str):
    counts: defaultdict[str, tuple[int, bool, list[tuple]]] = defaultdict(
        lambda: (0, False, [])
    )

    for resource_path, resource_key, resource_range in __SEMANTIC_RANGE_INDEX:
        if not constants.RESOURCE_DEF.match(resource_key):
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


if __name__ == "__main__":
    server.start_io()
