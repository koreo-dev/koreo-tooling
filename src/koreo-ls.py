from collections import defaultdict
from pathlib import Path
import copy
import os

os.environ["KOREO_DEV_TOOLING"] = "true"

import nanoid
import yaml

from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument
from lsprotocol import types

from koreo import cache
from koreo.function_test.registry import get_function_tests
from koreo.function_test.run import run_function_test
from koreo.function_test.structure import FunctionTest
from koreo.result import is_unwrapped_ok
from koreo.workflow.structure import Workflow, ErrorStep

from koreo_tooling import constants
from koreo_tooling.analysis import call_arg_compare
from koreo_tooling.indexing import (
    IndexingLoader,
    TokenTypes,
    _RANGE_KEY,
    _SEMANTIC_TOKENS_KEY,
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


@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
async def change_workspace_config(params):
    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug,
            message=f"folders: {server.workspace.folders}",
        )
    )

    suffixes = ("yaml", "yml", "koreo")

    for folder_key in server.workspace.folders:
        path = Path(server.workspace.get_text_document(folder_key).path)

        for suffix in suffixes:
            for match in path.rglob(f"*.{suffix}"):
                server.window_log_message(
                    params=types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"file: {match}",
                    )
                )

                doc = server.workspace.get_text_document(f"{match}")
                await _handle_file(doc=doc)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def open_processor(params):
    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug, message=f"loading: {params.text_document.uri}"
        )
    )

    doc = server.workspace.get_text_document(params.text_document.uri)
    await _handle_file(doc=doc)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def change_processor(params):
    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug, message=f"changed: {params.text_document.uri}"
        )
    )

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
    types.SemanticTokensLegend(token_types=TokenTypes, token_modifiers=[]),
)
async def semantic_tokens_full(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc.path in __SEMANTIC_TOKEN_INDEX:
        await _handle_file(doc=doc)

    tokens = __SEMANTIC_TOKEN_INDEX[doc.path]
    return types.SemanticTokens(data=tokens)


async def _handle_file(doc: TextDocument):
    has_errors = False
    _reset_file_state(doc.path)

    try:
        has_errors = await _process_file(doc=doc)
    except Exception as err:
        server.window_log_message(
            params=types.LogMessageParams(
                type=types.MessageType.Error,
                message=f"Error parsing file ({doc.path}): {err}",
            )
        )
        return

    _process_workflows(path=doc.path)

    await _run_function_tests(path=doc.path)

    dupes = _check_for_duplicate_resources(path=doc.path)
    has_errors = has_errors or dupes

    if __DIAGNOSTICS[doc.path]:
        server.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=doc.uri, version=doc.version, diagnostics=__DIAGNOSTICS[doc.path]
            )
        )


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


async def _process_file(
    doc: TextDocument,
):
    has_errors = False

    path = doc.path

    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug,
            message=f"processing file ({path})",
        )
    )

    yaml_blocks = yaml.load_all(doc.source, Loader=IndexingLoader)
    for yaml_block in yaml_blocks:
        tokens = yaml_block.get(_SEMANTIC_TOKENS_KEY)
        __SEMANTIC_TOKEN_INDEX[path].extend(tokens)

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
    dupes = False

    for resource_index_key in __PATH_RESOURCE_INDEX[path]:
        for resource_range in __RESOURCE_RANGE_INDEX[resource_index_key][path]:
            dupe_found = _check_for_duplicate_resource(
                path, resource_range, resource_index_key
            )
            dupes = dupes or dupe_found

    return dupes


def _check_for_duplicate_resource(
    path: str, resource_range: types.Range, resource_index_key: str
):
    for check_path, ranges in __RESOURCE_RANGE_INDEX[resource_index_key].items():
        for check_range in ranges:
            if check_path == path and check_range == resource_range:
                continue

            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"Mulitiple instances of {resource_index_key}.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )
            return True

    return False


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


async def _run_function_tests(path: str):
    tests_to_run = []
    for resource_key in __PATH_RESOURCE_INDEX[path]:
        if resource_key.startswith("FunctionTest:"):
            test_name = resource_key.split(":", 1)[1]
            tests_to_run.append(test_name)

        if resource_key.startswith("Function:"):
            function_name = resource_key.split(":", 1)[1]
            function_tests = get_function_tests(function_name)
            tests_to_run.extend(function_tests)

    for test_key in tests_to_run:
        test = cache.get_resource_from_cache(
            resource_class=FunctionTest, cache_key=test_key
        )
        if not test:
            server.window_log_message(
                params=types.LogMessageParams(
                    type=types.MessageType.Error,
                    message=f"Failed to find FunctionTest ('{test_key}') in Koreo cache.",
                )
            )
            continue

        await _run_function_test(path, test_key, test)


async def _run_function_test(path: str, test_name: str, test: FunctionTest):
    test_outcome = await run_function_test(location=test_name, function_test=test)

    if not is_unwrapped_ok(test_outcome):
        ranges = __RESOURCE_RANGE_INDEX[f"FunctionTest:{test_name}"][path]
        for range in ranges:
            __DIAGNOSTICS[path].append(
                types.Diagnostic(
                    message=f"FunctionTest ('{test_name}') failed with '{test_outcome.message}'.",
                    severity=types.DiagnosticSeverity.Error,
                    range=range,
                )
            )

    actual, expected = test_outcome
    wrong_fields = _dict_compare(actual, expected, base="")

    if not wrong_fields:
        return

    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Info,
            message=f"{test_name}: ('{wrong_fields}')",
        )
    )

    test_ranges = __RESOURCE_RANGE_INDEX[f"FunctionTest:{test_name}"][path]
    for test_range in test_ranges:
        __DIAGNOSTICS[path].append(
            types.Diagnostic(
                message=f"Mismatch: {wrong_fields}",
                severity=types.DiagnosticSeverity.Error,
                range=types.Range(
                    start=test_range.start,
                    end=types.Position(line=test_range.start.line + 5, character=0),
                ),
            )
        )


def _dict_compare(lhs: dict, rhs: dict, base: str):
    differences = []

    lhs_keys = set(lhs.keys())
    rhs_keys = set(rhs.keys())

    differences.extend(f"{base}.{key}" for key in lhs_keys.difference(rhs_keys))
    differences.extend(f"{base}.{key}" for key in rhs_keys.difference(lhs_keys))

    for mutual_key in lhs_keys.intersection(rhs_keys):
        lhs_value = lhs[mutual_key]
        rhs_value = rhs[mutual_key]

        key = f"{base}.{mutual_key}"

        if type(lhs_value) != type(rhs_value):
            differences.append(key)
            continue

        if isinstance(lhs_value, dict):
            differences.extend(_dict_compare(lhs_value, rhs_value, base=key))
            continue

        if isinstance(lhs_value, list):
            if not _values_match(lhs_value, rhs_value):
                differences.append(key)

            continue

        if not _values_match(lhs_value, rhs_value):
            differences.append(key)

    return differences


def _values_match(lhs, rhs) -> bool:
    if type(lhs) != type(rhs):
        return False

    if isinstance(lhs, dict):
        diffs = _dict_compare(lhs, rhs, base="")
        return not diffs

    if isinstance(lhs, list):
        if len(lhs) != len(rhs):
            return False

        for lhs_value, rhs_value in zip(lhs, rhs):
            if not _values_match(lhs_value, rhs_value):
                return False

        return True

    return lhs == rhs


if __name__ == "__main__":
    server.start_io()
