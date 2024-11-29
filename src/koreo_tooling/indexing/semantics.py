from __future__ import annotations
from functools import reduce
from typing import Literal, NamedTuple, NotRequired, TypedDict, get_args
import enum
import operator

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


    key: str
class SemanticAnchor(NamedTuple):
    abs_position: Position
    rel_position: Position
    children: list[SemanticAnchor | SemanticNode] | None = None


    key: str
class SemanticNode(NamedTuple):
    position: Position
    anchor_rel: Position
    length: int
    node_type: TokenType = ""
    modifier: list[Modifier] | None = None
    children: list[SemanticNode] | None = None
    diagnostic: NodeDiagnostic | None = None


class SemanticStructure(TypedDict):
    type: NotRequired[TokenType]
    modifier: NotRequired[list[Modifier]]
    sub_structure: NotRequired[dict[str, SemanticStructure]]


def flatten(
    nodes: SemanticAnchor | SemanticNode | list[SemanticAnchor | SemanticNode],
) -> list[SemanticNode]:
    if isinstance(nodes, (SemanticAnchor, SemanticNode)):
        return flatten_node(nodes)

    flattened = []

    for node in nodes:
        flattened.extend(flatten_node(node))

    return flattened


def flatten_node(node: SemanticAnchor | SemanticNode) -> list[SemanticNode]:
    flattened = []
    if isinstance(node, SemanticNode):
        flattened.append(node._replace(children=None))

    if not node.children:
        return flattened

    for child_node in node.children:
        flattened.extend(flatten_node(child_node))

    return flattened


def to_lsp_semantics(nodes: list[SemanticNode]) -> list[int]:
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


def extract_diagnostics(nodes: list[SemanticNode]) -> list[SemanticNode]:
    return [node for node in nodes if node.diagnostic]


def generate_key_range_index(
    nodes: SemanticAnchor | SemanticNode | list[SemanticAnchor | SemanticNode],
    anchor: SemanticAnchor | None = None,
) -> list:
    index = []

    if isinstance(nodes, SemanticAnchor):
        if nodes.key:
            # TODO: Range?
            index.append((nodes.key, nodes.abs_position))

        if nodes.children:
            index.extend(generate_key_range_index(nodes=nodes.children, anchor=nodes))

        return index

    if isinstance(nodes, SemanticNode):
        if nodes.key and anchor:
            index.append((nodes.key, _compute_range(nodes, anchor=anchor)))

        if nodes.children:
            index.extend(generate_key_range_index(nodes=nodes.children, anchor=anchor))

        return index

    for node in nodes:
        index.extend(generate_key_range_index(nodes=node, anchor=anchor))

    return index


def _compute_range(node: SemanticNode, anchor: SemanticAnchor) -> types.Range:
    return types.Range(
        start=types.Position(
            line=anchor.abs_position.line + node.anchor_rel.line,
            character=node.anchor_rel.offset,
        ),
        end=types.Position(
            line=anchor.abs_position.line + node.anchor_rel.line,
            character=node.anchor_rel.offset + node.length,
        ),
    )
