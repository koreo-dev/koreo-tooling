from functools import reduce
from typing import Any, Generator, NamedTuple, Sequence
import operator

import yaml.parser
import yaml.scanner
import yaml.loader

from pygls.workspace import TextDocument
from lsprotocol import types

from koreo import cache

from koreo_tooling.indexing import IndexingLoader, STRUCTURE_KEY
from koreo_tooling.indexing.semantics import (
    SemanticAnchor,
    SemanticNode,
    TokenTypes,
    compute_abs_range,
    extract_diagnostics,
    flatten,
    generate_key_range_index,
)

from koreo_tooling import constants
from koreo_tooling.langserver.rangers import block_range_extract

TypeIndex = {key: idx for idx, key in enumerate(TokenTypes)}


class SemanticRangeIndex(NamedTuple):
    uri: str
    name: str
    range: types.Range
    version: str | None = None


class ProccessResults(NamedTuple):
    semantic_tokens: Sequence[int] | None = None
    semantic_range_index: Sequence[SemanticRangeIndex] | None = None
    logs: Sequence[types.LogMessageParams] | None = None
    diagnostics: Sequence[types.Diagnostic] | None = None


async def process_file(doc: TextDocument) -> ProccessResults:
    uri = doc.uri

    semantic_tokens: list[int] = []
    semantic_range_index: list[SemanticRangeIndex] = []
    logs: list[types.LogMessageParams] = []
    diagnostics: list[types.Diagnostic] = []

    yaml_blocks = _load_all_yamls(doc.source, Loader=IndexingLoader, doc=doc)
    for yaml_block in yaml_blocks:
        match yaml_block:
            case YamlParseError(
                err=err, problem_pos=problem_pos, context_pos=context_pos
            ):
                logs.append(
                    types.LogMessageParams(
                        type=types.MessageType.Error,
                        message=f"Failed to parse YAML around {problem_pos} / {context_pos}",
                    )
                )

                last_line = len(doc.lines) - 1

                if problem_pos:
                    diagnostics.append(
                        types.Diagnostic(
                            message=err,
                            severity=types.DiagnosticSeverity.Error,
                            range=types.Range(
                                start=types.Position(
                                    line=problem_pos.line, character=0
                                ),
                                end=types.Position(
                                    line=problem_pos.line,
                                    character=len(
                                        doc.lines[min(problem_pos.line, last_line)]
                                    ),
                                ),
                            ),
                        )
                    )

                if context_pos:
                    diagnostics.append(
                        types.Diagnostic(
                            message=err,
                            severity=types.DiagnosticSeverity.Error,
                            range=types.Range(
                                start=types.Position(
                                    line=context_pos.line, character=0
                                ),
                                end=types.Position(
                                    line=context_pos.line,
                                    character=len(
                                        doc.lines[min(context_pos.line, last_line)]
                                    ),
                                ),
                            ),
                        )
                    )

                break

            case (block_hash, block_doc):
                block_result = await _process_block(
                    uri=uri,
                    yaml_block=block_doc,
                    doc=doc,
                    block_hash=block_hash,
                )

                if block_result.logs:
                    logs.extend(block_result.logs)

                if block_result.semantic_tokens:
                    semantic_tokens.extend(
                        value
                        for token in block_result.semantic_tokens
                        for value in token
                    )

                if block_result.semantic_range_index:
                    semantic_range_index.extend(block_result.semantic_range_index)

                    # TODO: Extract def and tag version in index?

                if block_result.diagnostics:
                    diagnostics.extend(block_result.diagnostics)

    return ProccessResults(
        semantic_range_index=semantic_range_index,
        semantic_tokens=semantic_tokens,
        logs=logs,
        diagnostics=diagnostics,
    )


class BlockResults(NamedTuple):
    semantic_tokens: Generator[tuple[int], None, None] | None = None
    semantic_range_index: Generator[SemanticRangeIndex, None, None] | None = None
    logs: Sequence[types.LogMessageParams] | None = None
    diagnostics: Sequence[types.Diagnostic] | None = None


async def _process_block(
    uri: str, yaml_block: dict, doc: TextDocument, block_hash: str
) -> BlockResults:
    try:
        api_version = yaml_block.get("apiVersion")
        kind = yaml_block.get("kind")
    except:
        return BlockResults(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Info,
                    message="Skipping empty block",
                )
            ]
        )

    semantic_anchor: SemanticAnchor | None = yaml_block.get(STRUCTURE_KEY)
    if not semantic_anchor:
        block_result = BlockResults(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Info,
                    message="Failed to load semantic anchor",
                )
            ]
        )
        return block_result

    semantic_range_index = (
        SemanticRangeIndex(uri=uri, name=node_key, range=node_range, version=block_hash)
        for node_key, node_range in generate_key_range_index(semantic_anchor)
    )

    flattened = flatten(semantic_anchor)
    semantic_tokens = _to_lsp_semantics(flattened)

    logs: list[types.LogMessageParams] = []
    diagnostics: list[types.Diagnostic] = []

    for node in extract_diagnostics(flattened):
        diagnostics.append(
            types.Diagnostic(
                message=node.diagnostic.message,
                severity=types.DiagnosticSeverity.Error,  # TODO: Map internal to LSP
                range=compute_abs_range(node, semantic_anchor),
            )
        )

    if api_version not in {
        constants.API_VERSION,
        constants.CRD_API_VERSION,
    }:
        api_version_block = block_range_extract(
            search_key="api_version",
            search_nodes=semantic_anchor.children,
            anchor=semantic_anchor,
        )
        match api_version_block:
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case None:
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case _:
                resource_range = compute_abs_range(api_version_block, semantic_anchor)

        diagnostics.append(
            types.Diagnostic(
                message=f"'{kind}.{api_version}' is not a Koreo Resource.",
                severity=types.DiagnosticSeverity.Information,
                range=resource_range,
            )
        )

        block_result = BlockResults(
            semantic_range_index=semantic_range_index,
            semantic_tokens=semantic_tokens,
            diagnostics=diagnostics,
        )
        return block_result

    if kind not in constants.PREPARE_MAP and kind != constants.CRD_KIND:
        kind_version_block = block_range_extract(
            search_key="kind",
            search_nodes=semantic_anchor.children,
            anchor=semantic_anchor,
        )
        match kind_version_block:
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case None:
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case _:
                resource_range = compute_abs_range(kind_version_block, semantic_anchor)

        diagnostics.append(
            types.Diagnostic(
                message=f"'{kind}' is not a supported Koreo Resource.",
                severity=types.DiagnosticSeverity.Information,
                range=resource_range,
            )
        )
        block_result = BlockResults(
            semantic_range_index=semantic_range_index,
            semantic_tokens=semantic_tokens,
            diagnostics=diagnostics,
        )
        return block_result

    resource_class, preparer = constants.PREPARE_MAP[kind]
    metadata = yaml_block.get("metadata", {})
    name = metadata.get("name", "missing-name")

    resource_version = f"{block_hash}"
    metadata["resourceVersion"] = resource_version

    raw_spec = yaml_block.get("spec", {})

    cached_system_data = {
        "uri": uri,
        "anchor": semantic_anchor,
    }

    try:
        await cache.prepare_and_cache(
            resource_class=resource_class,
            preparer=preparer,
            metadata=metadata,
            spec=raw_spec,
            _system_data=cached_system_data,
        )

    except Exception as err:
        resource_name_label = block_range_extract(
            search_key=f"{kind}:{name}:def",
            search_nodes=semantic_anchor.children,
            anchor=semantic_anchor,
        )
        match resource_name_label:
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case None:
                resource_range = _block_range(semantic_anchor=semantic_anchor, doc=doc)
            case _:
                resource_range = compute_abs_range(resource_name_label, semantic_anchor)

        diagnostics.append(
            types.Diagnostic(
                message=f"FAILED TO Extract ('{kind}.{api_version}') from {name} ({err}).",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )

    block_result = BlockResults(
        semantic_range_index=semantic_range_index,
        semantic_tokens=semantic_tokens,
        diagnostics=diagnostics,
        logs=logs,
    )
    return block_result


class YamlParseError(NamedTuple):
    err: str
    problem_pos: types.Position | None
    context_pos: types.Position | None


def _load_all_yamls(
    stream, Loader, doc
) -> Generator[tuple[str, dict] | YamlParseError, Any, None]:
    """
    Parse all YAML documents in a stream
    and produce corresponding Python objects.
    """
    loader = Loader(stream, doc=doc)
    try:
        while loader.check_data():
            try:
                yield loader.get_data()
            except (yaml.scanner.ScannerError, yaml.parser.ParserError) as err:
                problem_pos = None
                if err.problem_mark:
                    problem_pos = types.Position(
                        line=err.problem_mark.line, character=err.problem_mark.column
                    )

                context_pos = None
                if err.context_mark:
                    context_pos = types.Position(
                        line=err.context_mark.line, character=err.context_mark.column
                    )

                yield YamlParseError(
                    err=f"{err}", problem_pos=problem_pos, context_pos=context_pos
                )

    finally:
        loader.dispose()


def _to_lsp_semantics(nodes: Sequence[SemanticNode]) -> Generator[tuple, None, None]:
    for node in nodes:
        yield (
            node.position.line,
            node.position.character,
            node.length,
            TypeIndex[node.node_type],
            reduce(operator.or_, node.modifier, 0) if node.modifier else 0,
        )


def _block_range(semantic_anchor: SemanticAnchor, doc: TextDocument) -> types.Range:
    return types.Range(
        start=types.Position(
            line=semantic_anchor.abs_position.line,
            character=semantic_anchor.abs_position.character,
        ),
        end=types.Position(
            line=semantic_anchor.abs_position.line,
            character=len(doc.lines[semantic_anchor.abs_position.line]),
        ),
    )
