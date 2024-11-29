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


class Anchor(NamedTuple):
    key: str
    abs_position: Position
    rel_position: Position
    children: list[Anchor | NodeInfo] | None = None


class NodeInfo(NamedTuple):
    key: str
    position: Position
    anchor_rel: Position
    length: int
    node_type: TokenType = ""
    modifier: list[Modifier] | None = None
    children: list[NodeInfo] | None = None
    diagnostic: NodeDiagnostic | None = None


class SemanticStructure(TypedDict):
    type: NotRequired[TokenType]
    modifier: NotRequired[list[Modifier]]
    sub_structure: NotRequired[dict[str, SemanticStructure]]


def flatten(nodes: Anchor | NodeInfo | list[Anchor | NodeInfo]) -> list[NodeInfo]:
    if isinstance(nodes, (Anchor, NodeInfo)):
        return flatten_node(nodes)

    flattened = []

    for node in nodes:
        flattened.extend(flatten_node(node))

    return flattened


def flatten_node(node: Anchor | NodeInfo) -> list[NodeInfo]:
    flattened = []
    if isinstance(node, NodeInfo):
        flattened.append(
            NodeInfo(
                key=node.key,
                position=node.position,
                anchor_rel=node.anchor_rel,
                length=node.length,
                node_type=node.node_type,
                modifier=node.modifier,
                diagnostic=node.diagnostic,
            )
        )

    if not node.children:
        return flattened

    for child_node in node.children:
        flattened.extend(flatten_node(child_node))

    return flattened


def to_lsp_semantics(nodes: list[NodeInfo]) -> list[int]:
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


def extract_diagnostics(nodes: list[NodeInfo]) -> list[NodeInfo]:
    return [node for node in nodes if node.diagnostic]
