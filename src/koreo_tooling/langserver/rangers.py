from typing import Sequence

from lsprotocol import types

from koreo_tooling.indexing.semantics import (
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    anchor_local_key_search,
    compute_abs_range,
)


type SemanticReturn = SemanticAnchor | SemanticBlock | SemanticNode
type RangerError = list[types.Diagnostic]
type RangerReturns = SemanticReturn | RangerError | None


def block_range_extract(
    search_key: str,
    search_nodes: Sequence[SemanticAnchor | SemanticBlock | SemanticNode] | None,
    anchor: SemanticAnchor,
) -> RangerReturns:
    matches = anchor_local_key_search(search_key, search_nodes=search_nodes)

    if not matches:
        return None

    match, *extras = matches

    if extras:
        return [
            types.Diagnostic(
                message=f"Multiple instances of ('{search_key}').",
                severity=types.DiagnosticSeverity.Error,
                range=compute_abs_range(match, anchor),
            )
            for match in matches
        ]

    return match


def key_value_range_extract(
    search_key: str,
    search_nodes: Sequence[SemanticAnchor | SemanticBlock | SemanticNode] | None,
    anchor: SemanticAnchor,
) -> RangerReturns:
    key = block_range_extract(
        search_key=search_key, search_nodes=search_nodes, anchor=anchor
    )
    match key:
        case None:
            return None
        case list(block_diagnostics):
            return block_diagnostics

    if not key.children:
        return [
            types.Diagnostic(
                message=f"Missing value for ('{search_key}').",
                severity=types.DiagnosticSeverity.Warning,
                range=compute_abs_range(key, anchor),
            )
        ]

    value, *extras = key.children

    if extras:
        return [
            types.Diagnostic(
                message=f"Multiple children of ('{search_key}'), child {idx}.",
                severity=types.DiagnosticSeverity.Error,
                range=compute_abs_range(child, anchor),
            )
            for idx, child in enumerate(key.children)
        ]

    return value


def nested_range_extract(
    search_keys: list[str], search_nodes: Sequence, anchor: SemanticAnchor
) -> RangerReturns:
    while search_keys:
        search_key, *search_keys = search_keys
        next_node = block_range_extract(
            search_key=search_key,
            search_nodes=search_nodes,
            anchor=anchor,
        )
        match next_node:
            case None:
                return None
            case list(block_diagnostics):
                return block_diagnostics

        if not search_keys:
            return next_node

        if not next_node.children:
            return None

        search_nodes = next_node.children

    return None
