from __future__ import annotations
from functools import reduce
from typing import (
    Any,
    Literal,
    NamedTuple,
    NotRequired,
    Protocol,
    Sequence,
    TypedDict,
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
    path_key: str | None
    index_key: str | None
    anchor_rel_start: Position
    anchor_rel_end: Position
    children: Sequence[SemanticBlock | SemanticNode] | None = None


class SemanticNode(NamedTuple):
    position: Position
    anchor_rel: Position
    length: int
    path_key: str | None = None
    index_key: str | None = None
    node_type: TokenType = ""
    modifier: list[Modifier] | None = None
    children: Sequence[SemanticBlock | SemanticNode] | None = None
    diagnostic: NodeDiagnostic | None = None


class IndexFn(Protocol):
    def __call__(self, value: Any) -> str | None: ...


class SemanticStructure(TypedDict):
    type: NotRequired[TokenType]
    modifier: NotRequired[list[Modifier]]
    path_key_fn: NotRequired[IndexFn]
    index_key_fn: NotRequired[IndexFn]
    sub_structure: NotRequired[dict[str, SemanticStructure]]


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


def anchor_path_search(
    path_parts: Sequence[str],
    _search_nodes: (
        Sequence[SemanticAnchor | SemanticBlock | SemanticNode] | None
    ) = None,
) -> Sequence[SemanticNode]:
    if not _search_nodes:
        return []

    search_part, *remaining_parts = path_parts

    index = []
    for node in _search_nodes:
        match node:
            case SemanticAnchor(key=key):
                if not key or key != search_part:
                    continue

            case SemanticBlock(path_key=key):
                if key and key != search_part:
                    continue

            case SemanticNode(path_key=key):
                if not key or key != search_part:
                    continue

        if not remaining_parts and key:
            index.append(node)

            continue

        if not node.children:
            continue

        index.extend(
            anchor_path_search(
                path_parts=remaining_parts,
                _search_nodes=node.children,
            )
        )

    return index


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
