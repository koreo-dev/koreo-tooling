from __future__ import annotations
from functools import reduce
from typing import Any, Literal, NamedTuple, NotRequired, TypedDict, get_args
import enum
import operator

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode

from lsprotocol import types


_RANGE_KEY = "..range.."
_SEMANTIC_TOKENS_KEY = "..tokens.."
_STRUCTURE_KEY = "..structure.."

TokenType = Literal[
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


VALUE = "."
ALL = "*"


class SemanticStructure(TypedDict):
    type: NotRequired[TokenType]
    modifier: NotRequired[list[Modifier]]
    sub_structure: NotRequired[dict[str, SemanticStructure]]


SEMANTIC_TYPE_STRUCTURE: dict[str, dict[str, SemanticStructure]] = {
    "Function": {
        "apiVersion": {
            "sub_structure": {
                VALUE: {
                    "type": "namespace",
                    "modifier": [Modifier.definition],
                },
            },
        },
        "kind": {
            "sub_structure": {
                VALUE: {
                    "type": "type",
                },
            },
        },
        "metadata": {
            "sub_structure": {
                "name": {
                    "sub_structure": {
                        VALUE: {
                            "type": "function",
                            "modifier": [Modifier.definition],
                        },
                    },
                },
                "namespace": {
                    "sub_structure": {
                        VALUE: {
                            "type": "namespace",
                        },
                    },
                },
            },
        },
        "spec": {
            "sub_structure": {
                "staticResource": {
                    "sub_structure": {
                        "behavior": {
                            "sub_structure": {
                                "load": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                                "create": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "number"},
                                    },
                                },
                                "update": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                                "delete": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                            },
                        },
                    },
                },
                "inputValidators": {
                    "sub_structure": {
                        "type": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "class"},
                            },
                        },
                        "message": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                        "test": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                    },
                },
                "outcome": {
                    "sub_structure": {
                        "okValue": {
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
    "Workflow": {
        "apiVersion": {
            "sub_structure": {
                VALUE: {"type": "namespace", "modifier": [Modifier.definition]},
            },
        },
        "kind": {"sub_structure": {VALUE: {"type": "type"}}},
        "metadata": {
            "type": "keyword",
            "sub_structure": {
                "name": {
                    "type": "keyword",
                    "sub_structure": {
                        VALUE: {
                            "type": "class",
                            "modifier": [Modifier.definition],
                        },
                    },
                },
                "namespace": {
                    "type": "keyword",
                    "sub_structure": {
                        VALUE: {
                            "type": "namespace",
                        },
                    },
                },
            },
        },
        "spec": {
            "type": "keyword",
            "sub_structure": {
                "crdRef": {
                    "type": "typeParameter",
                    "sub_structure": {
                        "apiGroup": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "namespace"},
                            },
                        },
                        "version": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                        "kind": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "class"},
                            },
                        },
                    },
                },
                "steps": {
                    "type": "keyword",
                    "sub_structure": {
                        "label": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {
                                    "type": "event",
                                    "modifier": [Modifier.definition],
                                },
                            },
                        },
                        "functionRef": {
                            "type": "property",
                            "sub_structure": {
                                "name": {
                                    "type": "property",
                                    "sub_structure": {
                                        VALUE: {"type": "function"},
                                    },
                                },
                            },
                        },
                        "inputs": {
                            "type": "property",
                            "sub_structure": {
                                ALL: {
                                    "type": "variable",
                                    "sub_structure": {
                                        VALUE: {"type": "argument"},
                                    },
                                }
                            },
                        },
                    },
                },
            },
        },
    },
    ALL: {
        ALL: {
            "type": "keyword",
        },
    },
}


class IndexingLoader(SafeLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_doc_start = (0, 0)

    def construct_document(self, node):
        doc = super().construct_document(node)

        doc_kind = doc.get("kind")
        doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(doc_kind, {})

        structure, doc_last_pos = extract_semantic_structure_info(
            key_path="",
            last_token_abs_start=self.last_doc_start,
            node=node,
            type_hint_map=doc_semantics,
        )
        doc[_STRUCTURE_KEY] = structure
        doc[_SEMANTIC_TOKENS_KEY] = to_lsp_semantics(structure)
        self.last_doc_start = doc_last_pos

        return doc

    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node=node, deep=deep)
        mapping[_RANGE_KEY] = types.Range(
            start=types.Position(
                line=node.start_mark.line, character=node.start_mark.column
            ),
            end=types.Position(line=node.end_mark.line, character=node.end_mark.column),
        )

        return mapping


def extract_semantic_structure_info(
    key_path: str,
    last_token_abs_start: tuple[int, int],
    node,
    type_hint_map: dict[str, SemanticStructure],
):
    if isinstance(node, MappingNode):
        semantic_nodes = []
        new_last_start = last_token_abs_start
        for key, value in node.value:
            hints = type_hint_map.get(key.value, {})
            if not hints:
                hints = type_hint_map.get(ALL, {})

            key_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}._{key.value}_",
                last_token_abs_start=new_last_start,
                node=key,
                type_hint=hints.get("type", "keyword"),
                modifier=hints.get("modifier", []),
                type_hint_map={},
            )
            semantic_nodes.extend(key_semantic_nodes)

            sub_structure = hints.get("sub_structure", {})
            value_semantic_info = sub_structure.get(VALUE, {})

            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}.{key.value}",
                last_token_abs_start=new_last_start,
                node=value,
                type_hint=value_semantic_info.get("type"),
                modifier=value_semantic_info.get("modifier", []),
                type_hint_map=sub_structure,
            )
            semantic_nodes.extend(value_semantic_nodes)

        return semantic_nodes, new_last_start

    if isinstance(node, SequenceNode):
        semantic_nodes = []
        new_last_start = last_token_abs_start
        for idx, value in enumerate(node.value):
            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}.{idx}",
                last_token_abs_start=new_last_start,
                node=value,
                type_hint=None,
                modifier=[],
                type_hint_map=type_hint_map,
            )
            semantic_nodes.extend(value_semantic_nodes)
        return semantic_nodes, new_last_start

    value_semantic_info = type_hint_map.get(VALUE, {})

    return _extract_value_semantic_info(
        key_path=key_path,
        last_token_abs_start=last_token_abs_start,
        node=node,
        type_hint=value_semantic_info.get("type"),
        modifier=value_semantic_info.get("modifier", []),
        type_hint_map=type_hint_map,
    )


def _extract_value_semantic_info(
    key_path: str,
    last_token_abs_start: tuple[int, int],
    node,
    type_hint: TokenType | None,
    modifier: list[Modifier],
    type_hint_map: dict[str, SemanticStructure],
):
    if isinstance(node, (MappingNode, SequenceNode)):
        return extract_semantic_structure_info(
            key_path=key_path,
            last_token_abs_start=last_token_abs_start,
            node=node,
            type_hint_map=type_hint_map,
        )

    if type_hint:
        node_type = type_hint
    else:
        tag_kind = node.tag.rsplit(":", 1)[-1]
        if tag_kind in {"int", "float", "bool"}:
            node_type = "number"
        else:
            node_type = "string"

    last_line, last_column = last_token_abs_start

    node_line = node.start_mark.line
    node_column = node.start_mark.column

    nodes = []
    while True:
        nodes.append(
            NodeInfo(
                key=key_path,
                position=RelativePosition(
                    line_offset=node_line - last_line,
                    char_offset=(
                        node_column - (0 if node_line > last_line else last_column)
                    ),
                    length=len(node.value),
                ),
                node_type=node_type,
                modifier=modifier,
            )
        )

        if node_line >= node.end_mark.line:
            break

        last_line = node_line
        last_column = node_column

        node_line += 1
        node_column = 0

    return (
        nodes,
        (node_line, node_column),
    )


def to_lsp_semantics(nodes: list[NodeInfo]) -> list[int]:
    semantics = []
    for node in nodes:
        semantics.extend(
            [
                node.position.line_offset,
                node.position.char_offset,
                node.position.length,
                TypeIndex[node.node_type],
                reduce(operator.or_, node.modifier, 0),
            ]
        )

    return semantics


STRIP_KEYS = set([_RANGE_KEY, _SEMANTIC_TOKENS_KEY])


def range_stripper(resource: Any):
    if isinstance(resource, dict):
        return {
            key: range_stripper(value)
            for key, value in resource.items()
            if key not in STRIP_KEYS
        }

    if isinstance(resource, list):
        return [range_stripper(value) for value in resource]

    return resource
