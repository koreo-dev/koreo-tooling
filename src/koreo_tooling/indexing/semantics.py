from __future__ import annotations
from typing import Literal, NamedTuple, NotRequired, TypedDict, get_args
import enum

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


class RelativePosition(NamedTuple):
    line_offset: int
    char_offset: int
    length: int


class NodeInfo(NamedTuple):
    key: str
    position: RelativePosition
    node_type: TokenType
    modifier: list[Modifier]
    children: list[NodeInfo] | None


class SemanticStructure(TypedDict):
    type: NotRequired[TokenType]
    modifier: NotRequired[list[Modifier]]
    sub_structure: NotRequired[dict[str, SemanticStructure]]


def flatten(nodes: list[NodeInfo]) -> list[NodeInfo]:
    flattened = []

    for node in nodes:
        flattened.extend(flatten_node(node))

    return flattened


def flatten_node(node: NodeInfo) -> list[NodeInfo]:
    flattened = [
        NodeInfo(
            key=node.key,
            position=node.position,
            node_type=node.node_type,
            modifier=node.modifier,
            children=None,
        )
    ]

    if not node.children:
        return flattened

    for child_node in node.children:
        flattened.extend(flatten_node(child_node))

    return flattened
