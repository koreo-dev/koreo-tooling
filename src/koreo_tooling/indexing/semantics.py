from __future__ import annotations
from dataclasses import dataclass
from functools import reduce
from typing import (
    Any,
    Literal,
    NamedTuple,
    Protocol,
    Sequence,
    get_args,
)
import enum
import operator

from lsprotocol import types

TokenType = Literal[
    "",
    "argument",
    "class",
    "comment",
    "decorator",
    "enum",
    "enumMember",
    "event",
    "function",
    "interface",
    "keyword",
    "macro",
    "method",
    "modifier",
    "namespace",
    "number",
    "operator",
    "parameter",
    "property",
    "regexp",
    "string",
    "struct",
    "type",
    "typeParameter",
    "variable",
]

TokenTypes = get_args(TokenType)
TypeIndex = {key: idx for idx, key in enumerate(TokenTypes)}


class Modifier(enum.IntFlag):
    declaration = enum.auto()
    definition = enum.auto()
    readonly = enum.auto()
    static = enum.auto()
    deprecated = enum.auto()
    abstract = enum.auto()
    modification = enum.auto()
    documentation = enum.auto()
    defaultLibrary = enum.auto()


TokenModifiers = [modifier.name for modifier in Modifier]


class Severity(enum.IntFlag):
    debug = enum.auto()
    info = enum.auto()
    warning = enum.auto()
    error = enum.auto()


class NodeDiagnostic(NamedTuple):
    message: str
    severity: Severity


class Position(NamedTuple):
    line: int
    offset: int


class SemanticAnchor(NamedTuple):
    key: str | None
    abs_position: Position
    rel_position: Position
    children: Sequence[SemanticBlock | SemanticNode] | None = None


class SemanticBlock(NamedTuple):
    local_key: str | None
    index_key: str | None
    anchor_rel_start: Position
    anchor_rel_end: Position
    children: Sequence[SemanticBlock | SemanticNode] | None = None


class SemanticNode(NamedTuple):
    position: Position
    anchor_rel: Position
    length: int
    local_key: str | None = None
    index_key: str | None = None
    node_type: TokenType = ""
    modifier: list[Modifier] | None = None
    children: Sequence[SemanticBlock | SemanticNode] | None = None
    diagnostic: NodeDiagnostic | None = None


class IndexFn(Protocol):
    def __call__(self, value: Any) -> str | None: ...


type SemanticStructureMap = dict[str, SemanticStructure]


@dataclass
class SemanticStructure:
    type: TokenType = ""
    modifier: list[Modifier] | None = None
    local_key_fn: IndexFn | None = None
    index_key_fn: IndexFn | None = None
    sub_structure: SemanticStructureMap | SemanticStructure | None = None


def flatten(
    nodes: (
        SemanticAnchor
        | SemanticBlock
        | SemanticNode
        | Sequence[SemanticAnchor | SemanticNode]
    ),
) -> Sequence[SemanticNode]:
    if isinstance(nodes, (SemanticAnchor, SemanticBlock, SemanticNode)):
        return flatten_node(nodes)

    flattened = []

    for node in nodes:
        flattened.extend(flatten_node(node))

    return flattened


def flatten_node(
    node: SemanticAnchor | SemanticBlock | SemanticNode,
) -> Sequence[SemanticNode]:
    flattened = []
    if isinstance(node, SemanticNode):
        flattened.append(node._replace(children=None))

    if not node.children:
        return flattened

    for child_node in node.children:
        flattened.extend(flatten_node(child_node))

    return flattened


def to_lsp_semantics(nodes: Sequence[SemanticNode]) -> Sequence[int]:
    semantics = []
    for node in nodes:
        semantics.extend(
            [
                node.position.line,
                node.position.offset,
                node.length,
                TypeIndex[node.node_type],
                reduce(operator.or_, node.modifier, 0) if node.modifier else 0,
            ]
        )

    return semantics


def extract_diagnostics(nodes: Sequence[SemanticNode]) -> Sequence[SemanticNode]:
    return [node for node in nodes if node.diagnostic]


def generate_key_range_index(
    nodes: (
        SemanticAnchor
        | SemanticBlock
        | SemanticNode
        | Sequence[SemanticBlock | SemanticNode]
    ),
    anchor: SemanticAnchor | None = None,
) -> Sequence[tuple[str, Position]]:
    index = []

    match nodes:
        case SemanticAnchor(key=key, abs_position=abs_position, children=children):
            if key:
                index.append((key, abs_position))

            if children:
                index.extend(generate_key_range_index(nodes=children, anchor=nodes))

            return index

        case SemanticBlock(index_key=index_key, children=children):
            if index_key and anchor:
                index.append((index_key, compute_abs_range(nodes, anchor=anchor)))

            if children:
                index.extend(generate_key_range_index(nodes=children, anchor=anchor))

            return index

        case SemanticNode(index_key=index_key, children=children):
            if index_key and anchor:
                index.append((index_key, compute_abs_range(nodes, anchor=anchor)))

            if children:
                index.extend(generate_key_range_index(nodes=children, anchor=anchor))

            return index

    for node in nodes:
        index.extend(generate_key_range_index(nodes=node, anchor=anchor))

    return index


def anchor_local_key_search(
    search_key: str,
    search_nodes: Sequence[SemanticAnchor | SemanticBlock | SemanticNode] | None = None,
) -> Sequence[SemanticAnchor | SemanticBlock | SemanticNode]:
    if not search_nodes or not search_key:
        return []

    index = []
    for node in search_nodes:
        match node:
            case SemanticAnchor(key=key):
                if key and key == search_key:
                    index.append(node)

            case SemanticBlock(local_key=local_key):
                if local_key and local_key == search_key:
                    index.append(node)

            case SemanticNode(local_key=local_key):
                if search_key and search_key == local_key:
                    index.append(node)

        if not node.children:
            continue

        index.extend(
            anchor_local_key_search(
                search_key=search_key,
                search_nodes=node.children,
            )
        )

    return index


def compute_abs_position(
    rel_position: Position, abs_position: Position, length: int = 0
) -> types.Position:
    return types.Position(
        line=abs_position.line + rel_position.line,
        character=rel_position.offset + length,
    )


def compute_abs_range(
    node: SemanticBlock | SemanticNode, anchor: SemanticAnchor
) -> types.Range:
    match node:
        case SemanticNode(anchor_rel=anchor_rel, length=length):
            return types.Range(
                start=types.Position(
                    line=anchor.abs_position.line + anchor_rel.line,
                    character=anchor_rel.offset,
                ),
                end=types.Position(
                    line=anchor.abs_position.line + anchor_rel.line,
                    character=anchor_rel.offset + length,
                ),
            )

        case SemanticBlock(
            anchor_rel_start=anchor_rel_start, anchor_rel_end=anchor_rel_end
        ):
            return types.Range(
                start=types.Position(
                    line=anchor.abs_position.line + anchor_rel_start.line,
                    character=anchor_rel_start.offset,
                ),
                end=types.Position(
                    line=anchor.abs_position.line + anchor_rel_end.line,
                    character=anchor_rel_end.offset,
                ),
            )

    # This should be impossible
    raise Exception(f"Bad node type ({type(node)})")
