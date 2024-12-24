from __future__ import annotations
from dataclasses import dataclass
from typing import (
    Any,
    Literal,
    NamedTuple,
    Protocol,
    Sequence,
    get_args,
)
import enum

from lsprotocol.types import Position, Range

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


TokenModifiers: Sequence[str] = [modifier.name for modifier in Modifier]


class Severity(enum.IntFlag):
    debug = enum.auto()
    info = enum.auto()
    warning = enum.auto()
    error = enum.auto()


class NodeDiagnostic(NamedTuple):
    message: str
    severity: Severity


class SemanticAnchor(NamedTuple):
    key: str | None
    abs_position: Position
    rel_position: Position
    children: Sequence[SemanticBlock | SemanticNode] | None = None


class SemanticBlock(NamedTuple):
    local_key: str | None
    index_key: str | None
    anchor_rel: Range
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


class FieldIndexFn(Protocol):
    def __call__(self, value: Any) -> tuple[str, str] | None: ...


type SemanticStructureMap = dict[str, SemanticStructure]


@dataclass
class SemanticStructure:
    type: TokenType = ""
    modifier: list[Modifier] | None = None
    local_key_fn: IndexFn | None = None
    index_key_fn: IndexFn | None = None
    field_index_key_fn: FieldIndexFn | None = None
    sub_structure: SemanticStructureMap | SemanticStructure | None = None
    strict_sub_structure_keys: bool = False


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
) -> Sequence[tuple[str, Range]]:
    index = []

    match nodes:
        case SemanticAnchor(key=key, children=children):
            if key:
                index.append((key, compute_abs_range(nodes, anchor=nodes)))

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


def generate_local_range_index(
    nodes: (
        SemanticAnchor
        | SemanticBlock
        | SemanticNode
        | Sequence[SemanticBlock | SemanticNode]
        | None
    ),
    anchor: SemanticAnchor | None = None,
) -> Sequence[tuple[str, Range]]:
    if not nodes:
        return []

    index = []

    match nodes:
        case SemanticAnchor(key=key, children=children):
            if key:
                index.append((key, compute_abs_range(nodes, anchor=nodes)))

            if children:
                index.extend(generate_local_range_index(nodes=children, anchor=nodes))

            return index

        case SemanticBlock(local_key=local_key, children=children):
            if local_key and anchor:
                index.append((local_key, compute_abs_range(nodes, anchor=anchor)))

            if children:
                index.extend(generate_local_range_index(nodes=children, anchor=anchor))

            return index

        case SemanticNode(local_key=local_key, children=children):
            if local_key and anchor:
                index.append((local_key, compute_abs_range(nodes, anchor=anchor)))

            if children:
                index.extend(generate_local_range_index(nodes=children, anchor=anchor))

            return index

    for node in nodes:
        index.extend(generate_local_range_index(nodes=node, anchor=anchor))

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
) -> Position:
    return Position(
        line=abs_position.line + rel_position.line,
        character=rel_position.character + length,
    )


def compute_abs_range(
    node: SemanticAnchor | SemanticBlock | SemanticNode, anchor: SemanticAnchor
) -> Range:
    match node:
        case SemanticAnchor(abs_position=abs_position):
            end_node = node
            while True:
                if not end_node.children:
                    break
                end_node = end_node.children[-1]

            match end_node:
                case SemanticAnchor(abs_position=abs_position):
                    end_pos = Position(
                        line=abs_position.line,
                        character=abs_position.character,
                    )
                case SemanticBlock(anchor_rel=anchor_rel):
                    end_pos = compute_abs_position(
                        anchor_rel.end, abs_position=abs_position
                    )
                case SemanticNode(anchor_rel=anchor_rel, length=length):
                    end_pos = compute_abs_position(
                        anchor_rel, abs_position=abs_position, length=length
                    )

            return Range(
                start=Position(
                    line=abs_position.line,
                    character=abs_position.character,
                ),
                end=end_pos,
            )

        case SemanticNode(anchor_rel=anchor_rel, length=length):
            return Range(
                start=Position(
                    line=anchor.abs_position.line + anchor_rel.line,
                    character=anchor_rel.character,
                ),
                end=Position(
                    line=anchor.abs_position.line + anchor_rel.line,
                    character=anchor_rel.character + length,
                ),
            )

        case SemanticBlock(anchor_rel=anchor_rel):
            return Range(
                start=Position(
                    line=anchor.abs_position.line + anchor_rel.start.line,
                    character=anchor_rel.start.character,
                ),
                end=Position(
                    line=anchor.abs_position.line + anchor_rel.end.line,
                    character=anchor_rel.end.character,
                ),
            )

    # This should be impossible
    raise Exception(f"Bad node type ({type(node)})")
