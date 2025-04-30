from collections import defaultdict
from pathlib import Path
import pathlib
from typing import Callable, NamedTuple, Sequence
import asyncio
import time

import logging

logger = logging.getLogger("koreo.ls")

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from koreo import schema

KOREO_LSP_NAME = "koreo-ls"
KOREO_LSP_VERSION = "v1beta1"
CRD_ROOT = pathlib.Path(__file__).parent.joinpath("crd")

server = LanguageServer(KOREO_LSP_NAME, KOREO_LSP_VERSION)

from koreo import cache
from koreo import registry
from koreo.function_test.structure import FunctionTest
from koreo.resource_function.structure import ResourceFunction
from koreo.resource_template.structure import ResourceTemplate
from koreo.result import is_unwrapped_ok
from koreo.value_function.structure import ValueFunction
from koreo.workflow.structure import Workflow

from koreo_tooling import constants
from koreo_tooling.function_test import TestResults
from koreo_tooling.indexing import TokenModifiers, TokenTypes, SemanticAnchor
from koreo_tooling.indexing.semantics import generate_local_range_index
from koreo_tooling.langserver.codelens import LENS_COMMANDS, EditResult, handle_lens
from koreo_tooling.langserver.fileprocessor import (
    ProccessResults,
    SemanticRangeIndex,
    process_file,
)
from koreo_tooling.langserver.function_test import run_function_tests
from koreo_tooling.langserver.hover import handle_hover
from koreo_tooling.langserver.orchestrator import handle_file, shutdown_handlers
from koreo_tooling.langserver.workflow import process_workflows


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
async def completions(params: types.CompletionParams):
    server.window_log_message(
        params=types.LogMessageParams(
            type=types.MessageType.Debug, message=f"completion params: {params}"
        )
    )

    # TODO: Add awareness of the context to surface the correct completions.
    # Use _lookup_current_line_info to find the context, then offer suitable
    # suggestion, probably similar to hover.

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

    # TODO: If we're confident about where they are, set this as is_incomplete=False
    return types.CompletionList(is_incomplete=True, items=items)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(params: types.HoverParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(uri=doc.uri, line=params.position.line)
    if not resource_info.index_match:
        return None

    hover_result = handle_hover(
        resource_key=resource_info.index_match.key,
        resource_key_range=resource_info.index_match.range,
        local_resource=resource_info.local_match,
        test_results=__TEST_RESULTS[doc.uri],
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

    test_results = __TEST_RESULTS[doc.uri]
    if not test_results:
        return []

    start_line = params.range.start.line
    end_line = params.range.end.line

    visible_tests = []
    for uri, maybe_resource, maybe_range, _ in __SEMANTIC_RANGE_INDEX:
        if uri != doc.uri:
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
        result = __TEST_RESULTS[doc.uri].get(test_name)

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


@server.feature(types.INITIALIZE)
async def initialize(params):
    await _process_workspace_directories()


@server.feature(types.TEXT_DOCUMENT_CODE_LENS)
def code_lens(params: types.CodeLensParams):
    """Return a list of code lens to insert into the given document.

    This method will read the whole document and identify each sum in the document and
    tell the language client to insert a code lens at each location.
    """
    doc = server.workspace.get_text_document(params.text_document.uri)

    test_results = __TEST_RESULTS[doc.uri]
    if not test_results:
        return []

    lens_result = handle_lens(
        doc_uri=params.text_document.uri,
        uri=doc.uri,
        doc_version=doc.version if doc.version else -1,
        test_results=test_results,
    )

    if lens_result.logs:
        for log in lens_result.logs:
            server.window_log_message(params=log)

    return lens_result.lens


def _lens_action_wrapper(fn: Callable[[str, TestResults], EditResult]):
    async def wrapper(args):
        if not args:
            return

        edit_args = args[0]

        doc_uri = edit_args["uri"]
        doc_version = edit_args["version"]
        test_name = edit_args["test_name"]

        doc = server.workspace.get_text_document(doc_uri)
        if doc.version != doc_version:
            return

        doc_uri = doc.uri

        test_result = __TEST_RESULTS[doc_uri][test_name]

        edit_result = fn(test_name, test_result)
        if edit_result.logs:
            for log in edit_result.logs:
                server.window_log_message(params=log)

        if edit_result.edits:
            # Apply the edit.
            server.workspace_apply_edit(
                types.ApplyWorkspaceEditParams(
                    edit=types.WorkspaceEdit(
                        document_changes=[
                            types.TextDocumentEdit(
                                text_document=types.OptionalVersionedTextDocumentIdentifier(
                                    uri=doc_uri,
                                    version=doc.version,
                                ),
                                edits=edit_result.edits,
                            )
                        ]
                    ),
                )
            )

    return wrapper


# Register Code Lens Commands
def _register_lens_commands(lens_commands):
    for command_name, command_fn in lens_commands:
        server.command(command_name=command_name)(_lens_action_wrapper(command_fn))


_register_lens_commands(LENS_COMMANDS)


@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
async def change_workspace_config(params):
    # TODO: This should probably load a config file that enumerates
    # namespaces or something.

    await _process_workspace_directories()


async def _process_workspace_directories():
    suffixes = ("k", "k.yaml", "k.yml", "koreo")

    for folder_key in server.workspace.folders:
        path = Path(server.workspace.get_text_document(folder_key).path)

        for suffix in suffixes:
            for match in path.rglob(f"*.{suffix}"):

                await handle_file(
                    file_uri=f"file://{match}",
                    monotime=time.monotonic(),
                    file_processor=_parse_file,
                )


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
async def open_processor(params):

    await handle_file(
        file_uri=params.text_document.uri,
        monotime=time.monotonic(),
        file_processor=_parse_file,
    )


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def change_processor(params):

    await handle_file(
        file_uri=params.text_document.uri,
        monotime=time.monotonic(),
        file_processor=_parse_file,
    )


class ResourceMatch(NamedTuple):
    key: str
    range: types.Range


class CurrentLineInfo(NamedTuple):
    index_match: ResourceMatch | None = None
    local_match: ResourceMatch | None = None


def _lookup_current_line_info(uri: str, line: int) -> CurrentLineInfo:
    possible_match: tuple[str, types.Range] | None = None
    for maybe_uri, maybe_key, maybe_range, _ in __SEMANTIC_RANGE_INDEX:
        if maybe_uri != uri:
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
    elif match := constants.FUNCTION_TEST_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=match.group("name")
        )
    elif match := constants.RESOURCE_FUNCTION_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=ResourceFunction, cache_key=match.group("name")
        )
    elif match := constants.VALUE_FUNCTION_ANCHOR.match(possible_match.key):
        cached = cache.get_resource_system_data_from_cache(
            resource_class=ValueFunction, cache_key=match.group("name")
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

    resource_info = _lookup_current_line_info(uri=doc.uri, line=params.position.line)
    if not resource_info.index_match:
        return []

    resource_key_root = resource_info.index_match.key.rsplit(":", 1)[0]
    search_key = f"{resource_key_root}:def"

    definitions = []
    for uri, maybe_key, maybe_range, _ in __SEMANTIC_RANGE_INDEX:
        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if maybe_key != search_key:
            continue

        definitions.append(types.Location(uri=uri, range=maybe_range))

    return definitions


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
async def goto_reference(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)

    resource_info = _lookup_current_line_info(uri=doc.uri, line=params.position.line)
    if not resource_info.index_match:
        return []

    resource_key_root = resource_info.index_match.key.rsplit(":", 1)[0]
    reference_key = f"{resource_key_root}:ref"
    definition_key = f"{resource_key_root}:def"

    references: list[types.Location] = []
    definitions: list[types.Location] = []
    for uri, maybe_key, maybe_range, _ in __SEMANTIC_RANGE_INDEX:
        if not isinstance(maybe_range, types.Range):
            # TODO: Get anchors setting a range
            continue

        if maybe_key == reference_key:
            references.append(types.Location(uri=uri, range=maybe_range))

        if maybe_key == definition_key:
            definitions.append(types.Location(uri=uri, range=maybe_range))

    return references + definitions


@server.feature(
    types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
    types.SemanticTokensLegend(token_types=TokenTypes, token_modifiers=TokenModifiers),
)
async def semantic_tokens_full(params: types.ReferenceParams):
    doc = server.workspace.get_text_document(params.text_document.uri)
    if not doc.uri in __SEMANTIC_TOKEN_INDEX:
        # Once processing has finished, a refresh will be issued.
        await handle_file(
            file_uri=params.text_document.uri,
            monotime=time.monotonic(),
            file_processor=_parse_file,
        )
        return

    tokens = __SEMANTIC_TOKEN_INDEX[doc.uri]
    return types.SemanticTokens(data=tokens)


@server.feature(types.SHUTDOWN)
async def shutdown(*_, **__):
    with open("/tmp/koreo-ls.log", "w") as outfile:
        outfile.write("shutting down")
        await shutdown_handlers()
        outfile.write("shut down complete")


class ParseNotification:
    pass


async def _parse_file(doc_uri: str):
    doc = server.workspace.get_text_document(doc_uri)

    file_analyzer_resource = registry.Resource(resource_type=FileAnalyzer, name=doc_uri)
    parse_notification_resource = registry.Resource(
        resource_type=ParseNotification, name=doc_uri
    )
    if file_analyzer_resource not in _ANALYZERS:
        registry.register(registerer=file_analyzer_resource)
        registry.subscribe(
            subscriber=file_analyzer_resource, resource=parse_notification_resource
        )

        analysis_task = asyncio.create_task(
            _analyzer_manager(file_analyzer_resource), name=doc_uri
        )
        _ANALYZERS[file_analyzer_resource] = analysis_task
        analysis_task.add_done_callback(
            lambda _: _ANALYZERS.__delitem__(file_analyzer_resource)
        )

    try:
        processing_result = await process_file(doc=doc)

        if processing_result.logs:
            for log in processing_result.logs:
                server.window_log_message(params=log)

    except Exception as err:
        return

    __PARSING_RESULT[doc_uri] = (doc.version, processing_result)

    registry.notify_subscribers(
        notifier=parse_notification_resource, event_time=time.monotonic()
    )


async def _run_doc_analysis(doc_uri: str):
    parse_info = __PARSING_RESULT.get(doc_uri)
    if not parse_info:
        return

    doc_version, parsing_result = parse_info

    await _analyze_file(
        doc_uri=doc_uri,
        doc_version=doc_version,
        parsing_result=parsing_result,
    )


async def _analyze_file(
    doc_uri: str,
    doc_version: int | None,
    parsing_result: ProccessResults,
):
    doc = server.workspace.get_text_document(doc_uri)

    if doc_version != doc.version:
        return

    diagnostics: list[types.Diagnostic] = []

    if parsing_result.diagnostics:
        diagnostics.extend(parsing_result.diagnostics)

    diagnostics.extend(
        _process_workflows(
            uri=doc.uri, semantic_range_index=parsing_result.semantic_range_index
        )
    )

    test_diagnostics, test_results = await _run_function_test(
        semantic_range_index=parsing_result.semantic_range_index
    )
    diagnostics.extend(test_diagnostics)

    if parsing_result.semantic_range_index:
        used_resources = _get_used_resources(parsing_result.semantic_range_index)
        current_resource_defs: dict[registry.Resource, str | None] = (
            _get_defined_resources(parsing_result.semantic_range_index)
        )
    else:
        used_resources: list[registry.Resource] = []
        current_resource_defs: dict[registry.Resource, str | None] = {}

    diagnostics.extend(
        _check_defined_resources(
            current_resource_defs.keys(), parsing_result.semantic_range_index
        )
    )

    old_resource_defs: dict[registry.Resource, str | None] = _get_defined_resources(
        [
            range_index
            for range_index in __SEMANTIC_RANGE_INDEX
            if range_index.uri == doc.uri
        ]
    )
    _reset_file_state(doc.uri)

    if parsing_result.semantic_tokens:
        __SEMANTIC_TOKEN_INDEX[doc.uri] = parsing_result.semantic_tokens
    else:
        # Will this break anything?
        __SEMANTIC_TOKEN_INDEX[doc.uri] = []

    if parsing_result.semantic_range_index:
        __SEMANTIC_RANGE_INDEX.extend(parsing_result.semantic_range_index)

    file_analyzer_resource = registry.Resource(resource_type=FileAnalyzer, name=doc_uri)
    used_resources.append(
        registry.Resource(resource_type=ParseNotification, name=doc_uri)
    )
    registry.subscribe_only_to(
        subscriber=file_analyzer_resource, resources=used_resources
    )
    if file_analyzer_resource not in _ANALYZERS:
        analysis_task = asyncio.create_task(
            _analyzer_manager(file_analyzer_resource), name=doc_uri
        )
        _ANALYZERS[file_analyzer_resource] = analysis_task
        analysis_task.add_done_callback(
            lambda _: _ANALYZERS.__delitem__(file_analyzer_resource)
        )

    deleted_resource_defs = set(old_resource_defs.keys()).difference(
        current_resource_defs.keys()
    )
    for deleted_resource in deleted_resource_defs:
        await cache.delete_from_cache(
            resource_class=deleted_resource.resource_type,
            cache_key=deleted_resource.name,
            version=old_resource_defs[deleted_resource],
        )

    __TEST_RESULTS[doc.uri] = test_results

    diagnostics.extend(_check_for_duplicate_resources(uri=doc.uri))

    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=doc_uri, version=doc_version, diagnostics=diagnostics
        )
    )


class FileAnalyzer: ...


_ANALYZERS: dict[registry.Resource[FileAnalyzer], asyncio.Task] = {}


async def _analyzer_manager(file_analyzer_resource: registry.Resource):
    queue = registry.register(registerer=file_analyzer_resource)
    last_time = 0
    while True:
        event = await queue.get()
        try:
            match event:
                case registry.Kill():
                    logger.info(f"Killing Analysis Manager ({file_analyzer_resource})")
                    break
                case registry.ResourceEvent(_, event_time):
                    await _run_doc_analysis(
                        doc_uri=file_analyzer_resource.name,
                    )
                    server.workspace_inlay_hint_refresh(None)
                    server.workspace_code_lens_refresh(None)
                    last_time = event_time
                    continue
        finally:
            queue.task_done()


def _get_defined_resources(semantic_range_index: Sequence[SemanticRangeIndex]):
    definitions = (
        (match.group("kind"), match.group("name"), version)
        for match, version in (
            (constants.RESOURCE_DEF.match(range_index.name), range_index.version)
            for range_index in semantic_range_index
        )
        if match
    )

    resources = dict[registry.Resource, str | None]()
    for definition in definitions:
        match definition:
            case ("ValueFunction", name, version):
                resource_key = registry.Resource(resource_type=ValueFunction, name=name)
            case ("ResourceFunction", name, version):
                resource_key = registry.Resource(
                    resource_type=ResourceFunction, name=name
                )
            case ("FunctionTest", name, version):
                resource_key = registry.Resource(resource_type=FunctionTest, name=name)
            case ("Workflow", name, version):
                resource_key = registry.Resource(resource_type=Workflow, name=name)
            case ("ResourceTemplate", name, version):
                resource_key = registry.Resource(
                    resource_type=ResourceTemplate, name=name
                )
            case _:
                continue

        resources[resource_key] = version
    return resources


def _get_used_resources(semantic_range_index: Sequence[SemanticRangeIndex]):
    references = set(
        (match.group("kind"), match.group("name"))
        for match in (
            constants.TOP_LEVEL_RESOURCE.match(range_index.name)
            for range_index in semantic_range_index
        )
        if match
    )

    resources: list[registry.Resource] = []
    for reference in references:
        match reference:
            case ("ResourceFunction", name):
                resources.append(
                    registry.Resource(resource_type=ResourceFunction, name=name)
                )
            case ("ValueFunction", name):
                resources.append(
                    registry.Resource(resource_type=ValueFunction, name=name)
                )
            case ("FunctionTest", name):
                resources.append(
                    registry.Resource(resource_type=FunctionTest, name=name)
                )
            case ("Workflow", name):
                resources.append(registry.Resource(resource_type=Workflow, name=name))
            case ("ResourceTemplate", name):
                resources.append(
                    registry.Resource(resource_type=ResourceTemplate, name=name)
                )
    return resources


def _check_defined_resources(
    resources: Sequence[registry.Resource],
    semantic_range_index: Sequence[SemanticRangeIndex] | None,
) -> Sequence[types.Diagnostic]:
    diagnostics: list[types.Diagnostic] = []

    if not semantic_range_index:
        return diagnostics

    resource_defs = {
        f"{match.group("kind")}:{match.group("name")}": match_range
        for match, match_range in (
            (constants.RESOURCE_DEF.match(range_index.name), range_index.range)
            for range_index in semantic_range_index
        )
        if match
    }

    for resource in resources:
        if resource.resource_type is Workflow:
            continue

        cached = cache.get_resource_from_cache(
            resource_class=resource.resource_type, cache_key=resource.name
        )

        if is_unwrapped_ok(cached):
            continue

        resource_range = resource_defs.get(
            f"{resource.resource_type.__name__}:{resource.name}"
        )
        if not resource_range:
            continue

        diagnostics.append(
            types.Diagnostic(
                message=cached.message,
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )
    return diagnostics


def _process_workflows(
    uri: str, semantic_range_index: Sequence[SemanticRangeIndex] | None
) -> list[types.Diagnostic]:
    if not semantic_range_index:
        return []

    workflows = []
    for _, resource_key, resource_range, _ in semantic_range_index:
        match = constants.WORKFLOW_NAME.match(resource_key)
        if not match:
            continue

        workflows.append((match.group("name"), resource_range))

    return process_workflows(uri=uri, workflows=workflows)


async def _run_function_test(
    semantic_range_index: Sequence[SemanticRangeIndex] | None,
) -> tuple[list[types.Diagnostic], dict[str, TestResults]]:
    """For the given `semantic_range_index`, get all `FunctionTests`. It will
    also accumulate all `ResourceFunction` and `ValueFunction` resources, the
    test runner will lookup all associated `FunctionTests` and run them as
    well. This allows tests and functions in different files, to cause the
    tests are re-run update test results.
    """
    if not semantic_range_index:
        return ([], {})

    test_range_map = {}
    tests_to_run = set[str]()
    resource_functions_to_test = set[str]()
    value_functions_to_test = set[str]()

    for _, resource_key, resource_range, _ in semantic_range_index:
        if match := constants.FUNCTION_TEST_NAME.match(resource_key):
            test_name = match.group("name")
            tests_to_run.add(test_name)
            test_range_map[test_name] = resource_range

        elif match := constants.RESOURCE_FUNCTION_NAME.match(resource_key):
            resource_functions_to_test.add(match.group("name"))

        elif match := constants.VALUE_FUNCTION_NAME.match(resource_key):
            value_functions_to_test.add(match.group("name"))

    if not (tests_to_run or value_functions_to_test or resource_functions_to_test):
        return ([], {})

    functions_to_test: dict[type, Sequence[str]] = {
        ValueFunction: tuple(value_functions_to_test),
        ResourceFunction: tuple(resource_functions_to_test),
    }

    test_results = await run_function_tests(
        tests_to_run=tests_to_run,
        functions_to_test=functions_to_test,
        test_range_map=test_range_map,
    )

    results = test_results.results
    if not results:
        results = {}

    if test_results.logs:
        for log in test_results.logs:
            server.window_log_message(params=log)

    if test_results.diagnostics:
        return (test_results.diagnostics, results)

    return ([], results)


# Globals? Are you evil or just stupid? Yes.
__PARSING_RESULT: dict[str, tuple[int | None, ProccessResults]] = {}
__TEST_RESULTS = defaultdict[str, dict[str, TestResults]](dict)
__SEMANTIC_TOKEN_INDEX: dict[str, Sequence[int]] = {}
__SEMANTIC_RANGE_INDEX: list[SemanticRangeIndex] = []


def _reset_file_state(uri: str):
    global __SEMANTIC_RANGE_INDEX

    __SEMANTIC_RANGE_INDEX = [
        range_index for range_index in __SEMANTIC_RANGE_INDEX if range_index.uri != uri
    ]

    if uri in __SEMANTIC_TOKEN_INDEX:
        del __SEMANTIC_TOKEN_INDEX[uri]

    if uri in __TEST_RESULTS:
        del __TEST_RESULTS[uri]


def _check_for_duplicate_resources(uri: str):
    counts: defaultdict[str, tuple[int, bool, list[tuple]]] = defaultdict(
        lambda: (0, False, [])
    )

    for resource_uri, resource_key, resource_range, _ in __SEMANTIC_RANGE_INDEX:
        if not constants.RESOURCE_DEF.match(resource_key):
            continue

        count, seen_in_uri, locations = counts[resource_key]
        locations.append((resource_uri, resource_range))
        counts[resource_key] = (
            count + 1,
            seen_in_uri or resource_uri == uri,
            locations,
        )

    duplicate_diagnostics: list[types.Diagnostic] = []

    for resource_key, (count, seen_in_uri, locations) in counts.items():
        if count <= 1 or not seen_in_uri:
            continue

        for resource_uri, resource_range in locations:
            if resource_uri != uri:
                continue

            duplicate_diagnostics.append(
                types.Diagnostic(
                    message=f"Mulitiple instances of {resource_key}.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )

    return duplicate_diagnostics


def main():
    schema.load_validators_from_files(path=CRD_ROOT)
    server.start_io()


if __name__ == "__main__":
    main()
