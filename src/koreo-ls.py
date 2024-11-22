from collections import defaultdict
from pathlib import Path
import copy
import os

os.environ["KOREO_DEV_TOOLING"] = "true"

import nanoid

from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument
from lsprotocol import types

from koreo import cache
from koreo.result import is_unwrapped_ok
from koreo.workflow.structure import Workflow, ErrorStep

from koreo_tooling import constants
from koreo_tooling.analysis import call_arg_compare
from koreo_tooling.function_test import TestResults, run_function_tests
from koreo_tooling.indexing import (
    IndexingLoader,
    TokenModifiers,
    TokenTypes,
    _RANGE_KEY,
    _SEMANTIC_TOKENS_KEY,
    _STRUCTURE_KEY,
    range_stripper,
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


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(params: types.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_key = None
    last_key = None
    last_key_start_line = 0
    for ref_range in __RANGE_REF_INDEX[doc.path].keys():
        range_start_line, range_end_line = _range_key_to_lines(ref_range)
        if range_start_line > params.position.line:
            continue

        if (
            range_start_line > last_key_start_line
            and range_end_line >= params.position.line
        ):
            last_key = ref_range
            last_key_start_line = range_start_line

    if not last_key:
        return None

    resource_key = __RANGE_REF_INDEX[doc.path][last_key]
    if not resource_key:
        return None

    if resource_key.startswith("FunctionTest"):
        test_name = resource_key.split(":")[1]
        result = __TEST_RESULTS[doc.path].get(test_name)
        hover_content = [f"# {test_name}"]
        if not result:
            hover_content.append(f"not yet ran")
        else:

            if result.success:
                hover_content.append(f"*success*")
            else:
                if result.messages:
                    hover_content.append("## Failure")
                    hover_content.extend(result.messages)

                if result.resource_field_errors:
                    hover_content.append("## Field Mismatches")
                    hover_content.extend(result.resource_field_errors)

                if result.outcome_fields_errors:
                    hover_content.append("## Outcome Mismatches")
                    hover_content.extend(result.outcome_fields_errors)

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

    hover_content = [f"# {resource_key}"]

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


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
async def goto_definitiion(params: types.DefinitionParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_key = None
    last_key = None
    last_key_start_line = 0
    for ref_range in __RANGE_REF_INDEX[doc.path].keys():
        range_start_line, range_end_line = _range_key_to_lines(ref_range)
        if range_start_line > params.position.line:
            continue

        if (
            range_start_line > last_key_start_line
            and range_end_line >= params.position.line
        ):
            last_key = ref_range
            last_key_start_line = range_start_line

    if not last_key:
        return []

    resource_key = __RANGE_REF_INDEX[doc.path][last_key]
    if not resource_key:
        return []

    definition_index = __RESOURCE_RANGE_INDEX[resource_key]

    definitions = []
    for def_path, def_ranges in definition_index.items():
        for def_range in def_ranges:
            definitions.append(types.Location(uri=def_path, range=def_range))

    return definitions


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
async def goto_reference(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_key = None
    last_key = None
    last_key_start_line = 0
    for ref_range in __RANGE_REF_INDEX[doc.path].keys():
        range_start_line, range_end_line = _range_key_to_lines(ref_range)
        if range_start_line > params.position.line:
            continue

        if (
            range_start_line > last_key_start_line
            and range_end_line >= params.position.line
        ):
            last_key = ref_range
            last_key_start_line = range_start_line

    if not last_key:
        return []

    resource_key = __RANGE_REF_INDEX[doc.path][last_key]
    if not resource_key:
        return []

    uses = __REF_RANGE_INDEX[resource_key]

    references = []

    for ref_path, ref_ranges in uses.items():
        for ref_range in ref_ranges:
            references.append(types.Location(uri=ref_path, range=ref_range))

    definition_index = __RESOURCE_RANGE_INDEX[resource_key]

    for def_path, def_ranges in definition_index.items():
        for def_range in def_ranges:
            references.append(types.Location(uri=def_path, range=def_range))

    return references


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


async def _handle_file(doc: TextDocument):
    _reset_file_state(doc.path)

    try:
        await _process_file(doc=doc)
    except Exception as err:
        server.window_log_message(
            params=types.LogMessageParams(
                type=types.MessageType.Error,
                message=f"Error parsing file ({doc.path}): {err}",
            )
        )
        return

    _process_workflows(path=doc.path)

    test_results = await run_function_tests(
        server=server,
        path_resources=__PATH_RESOURCE_INDEX[doc.path],
    )
    __TEST_RESULTS[doc.path] = test_results
    if test_results:
        for test_key, result in test_results.items():
            if result.success:
                continue

            messages = []
            if result.messages:
                messages.append(f"Failures: {'; '.join(result.messages)}")

            if result.resource_field_errors:
                messages.append(
                    f"Field errors: {', '.join(result.resource_field_errors)}"
                )

            if result.outcome_fields_errors:
                messages.append(
                    f"Outcome errors: {', '.join(result.outcome_fields_errors)}"
                )

            __DIAGNOSTICS[doc.path].extend(
                types.Diagnostic(
                    message=";".join(messages),
                    severity=types.DiagnosticSeverity.Error,
                    range=range,
                )
                for range in __RESOURCE_RANGE_INDEX[f"FunctionTest:{test_key}"][
                    doc.path
                ]
            )

    duplicate_diagnostics = _check_for_duplicate_resources(path=doc.path)
    if duplicate_diagnostics:
        __DIAGNOSTICS[doc.path].extend(duplicate_diagnostics)

    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=doc.uri, version=doc.version, diagnostics=__DIAGNOSTICS[doc.path]
        )
    )


__TEST_RESULTS = defaultdict[str, dict[str, TestResults]](defaultdict[str, TestResults])
__RANGE_INDEX = defaultdict[str, dict[str, dict]](defaultdict[str, dict])
__RANGE_REF_INDEX = defaultdict[str, dict[str, str]](defaultdict[str, str])
__SEMANTIC_TOKEN_INDEX = defaultdict[str, list[int]](list)


def _range_key(resource_range: types.Range):
    return f"{resource_range.start.line}.{resource_range.start.line}:{resource_range.end.line}.{resource_range.end.line}"


def _range_key_to_lines(key: str) -> tuple[int, int]:
    start, end = key.split(":")
    start_line = int(start.split(".")[0])
    end_line = int(end.split(".")[0])
    return (start_line, end_line)


__DIAGNOSTICS = defaultdict[str, list[types.Diagnostic]](list[types.Diagnostic])

__RESOURCE_RANGE_INDEX = defaultdict[str, dict[str, list[types.Range]]](
    lambda: defaultdict[str, list[types.Range]](list[types.Range])
)

__PATH_RESOURCE_INDEX = defaultdict[str, set[str]](set[str])

__REF_RANGE_INDEX = defaultdict[str, dict[str, list[types.Range]]](
    lambda: defaultdict[str, list[types.Range]](list[types.Range])
)
__PATH_REF_INDEX = defaultdict[str, set[str]](set[str])


def _reset_file_state(path_key: str):
    for resource_key in __PATH_RESOURCE_INDEX[path_key]:
        del __RESOURCE_RANGE_INDEX[resource_key][path_key]

    for resource_key in __PATH_REF_INDEX[path_key]:
        del __REF_RANGE_INDEX[resource_key][path_key]

    __PATH_RESOURCE_INDEX[path_key] = set()
    __PATH_REF_INDEX[path_key] = set()
    __DIAGNOSTICS[path_key] = []
    __RANGE_INDEX[path_key] = {}
    __RANGE_REF_INDEX[path_key] = {}
    __SEMANTIC_TOKEN_INDEX[path_key] = []
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
    has_errors = False

    path = doc.path


    yaml_blocks = _load_all_yamls(doc.source, Loader=IndexingLoader, doc=doc)
    for yaml_block in yaml_blocks:
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

        structure = yaml_block.get(_STRUCTURE_KEY)

        tokens = yaml_block.get(_SEMANTIC_TOKENS_KEY)
        __SEMANTIC_TOKEN_INDEX[path].extend(tokens)

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
            has_errors = True
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

        name = metadata.get("name")

        resource_index_key = f"{kind}:{name}"

        # resource_line = int(getattr(yaml_block, "__line__", 0))

        __RESOURCE_RANGE_INDEX[resource_index_key][path].append(resource_range)
        __PATH_RESOURCE_INDEX[path].add(resource_index_key)

        raw_spec = yaml_block.get("spec", {})

        __RANGE_INDEX[path][_range_key(resource_range)] = raw_spec

        __RANGE_REF_INDEX[path][
            _range_key(metadata.get(_RANGE_KEY))
        ] = resource_index_key

        try:
            range_stripped = range_stripper(copy.deepcopy(raw_spec))
            await cache.prepare_and_cache(
                resource_class=resource_class,
                preparer=preparer,
                metadata=metadata,
                spec=range_stripped,
                _system_data=structure,
            )

        except Exception as err:
            has_errors = True

            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"FAILED TO Extract ('{kind}.{api_version}') from {metadata.get('name')} ({err}).",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )

            raise

    return has_errors


def _check_for_duplicate_resources(path: str):
    duplicate_diagnostics: list[types.Diagnostic] = []

    for resource_index_key in __PATH_RESOURCE_INDEX[path]:
        for resource_range in __RESOURCE_RANGE_INDEX[resource_index_key][path]:
            duplicate_diagnostic = _check_for_duplicate_resource(
                path, resource_range, resource_index_key
            )
            if duplicate_diagnostic:
                duplicate_diagnostics.append(duplicate_diagnostic)

    return duplicate_diagnostics


def _check_for_duplicate_resource(
    path: str, resource_range: types.Range, resource_index_key: str
):
    for check_path, ranges in __RESOURCE_RANGE_INDEX[resource_index_key].items():
        for check_range in ranges:
            if check_path == path and check_range == resource_range:
                continue

            return types.Diagnostic(
                message=f"Mulitiple instances of {resource_index_key}.",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )

    return None


def _process_workflows(path: str):

    for resource_key in __PATH_RESOURCE_INDEX[path]:
        if not resource_key.startswith("Workflow:"):
            continue

        for resource_range in __RESOURCE_RANGE_INDEX[resource_key][path]:
            koreo_cache_key = resource_key.split(":", 1)[1]

            workflow = cache.get_resource_from_cache(
                resource_class=Workflow, cache_key=koreo_cache_key
            )

            if not workflow:
                server.window_log_message(
                    params=types.LogMessageParams(
                        type=types.MessageType.Error,
                        message=f"Failed to find Workflow ('{koreo_cache_key}') in Koreo cache ('{resource_key}').",
                    )
                )
                continue

            _process_workflow(
                path=path,
                resource_range=resource_range,
                raw_spec=__RANGE_INDEX[path][_range_key(resource_range)],
                workflow=workflow,
            )


def _process_workflow(
    path: str,
    resource_range: types.Range,
    raw_spec: dict,
    workflow: Workflow,
) -> bool:
    if not is_unwrapped_ok(workflow.steps_ready):
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow is not ready ({workflow.steps_ready.message}).",
                severity=types.DiagnosticSeverity.Warning,
                range=types.Range(
                    start=resource_range.start,
                    end=types.Position(line=resource_range.start.line + 5, character=0),
                ),
            )
        )

    has_step_error = False

    step_label_counts = defaultdict[str, int](lambda: 0)
    for step in workflow.steps:
        step_label_counts[step.label] += 1

    raw_steps = raw_spec.get("steps", [])

    for idx, step in enumerate(workflow.steps):
        raw_step = raw_steps[idx]
        step_range = raw_step.get(_RANGE_KEY)

        step_error = _process_workflow_step(path, step_range, step, raw_step)

        if step_label_counts[step.label] > 1:
            has_step_error = True
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Duplicate step label",
                    severity=types.DiagnosticSeverity.Error,
                    range=step_range,
                )
            )

        has_step_error = has_step_error or step_error

    if has_step_error:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Workflow steps are not ready.",
                severity=types.DiagnosticSeverity.Error,
                range=types.Range(
                    start=resource_range.start,
                    end=types.Position(line=resource_range.start.line + 5, character=0),
                ),
            )
        )

    return has_step_error


def _process_workflow_step(path, step_range, step, raw_step):
    has_error = False

    if isinstance(step, ErrorStep):
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Step ('{step.label}') not ready {step.outcome.message}.",
                severity=types.DiagnosticSeverity.Warning,
                range=step_range,
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

    ref_name = None
    ref_range = None

    function_ref_block = raw_step.get("functionRef")
    if function_ref_block:
        ref_name = f"Function:{function_ref_block.get("name")}"
        ref_range = function_ref_block.get(_RANGE_KEY, step_range)

    workflow_ref_block = raw_step.get("workflowRef")
    if workflow_ref_block:
        ref_name = f"Workflow:{function_ref_block.get("name")}"
        ref_range = workflow_ref_block.get(_RANGE_KEY, step_range)

    if ref_name and ref_range:
        __PATH_REF_INDEX[path].add(ref_name)
        __REF_RANGE_INDEX[ref_name][path].append(ref_range)
        __RANGE_REF_INDEX[path][_range_key(ref_range)] = ref_name

    raw_inputs = raw_step.get("inputs", {})
    inputs_range = raw_inputs.get(_RANGE_KEY, step_range)

    inputs = call_arg_compare(step.provided_input_keys, first_tier_inputs)
    for argument, (provided, expected) in inputs.items():
        if not expected and provided:
            raw_arg = raw_inputs.get(argument)
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Input ('{argument}') not expected. {raw_arg}.",
                    severity=types.DiagnosticSeverity.Warning,
                    range=inputs_range,
                )
            )
            has_error = True

        elif expected and not provided:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Missing input ('{argument}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=inputs_range,
                )
            )
            has_error = True

    return has_error


if __name__ == "__main__":
    server.start_io()
