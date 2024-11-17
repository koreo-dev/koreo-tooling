from typing import Any

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode

from lsprotocol import types


_RANGE_KEY = "..range.."
_SEMANTIC_TOKENS_KEY = "..tokens.."

TokenTypes = [
    "argument",
    "class",
    "enumMember",
    "function",
    "keyword",
    "namespace",
    "number",
    "parameter",
    "property",
    "string",
    "typeParameter",
]

SEMANTIC_TYPE_STRUCTURE = {
    "Function": {
        "spec": {
            "type": TokenTypes.index("keyword"),
            "type_map": {
                "staticResource": {
                    "type": TokenTypes.index("keyword"),
                    "type_map": {
                        "behavior": {
                            "type": TokenTypes.index("keyword"),
                            "type_map": {
                                "load": {
                                    "type": TokenTypes.index("parameter"),
                                    "type_map": {
                                        ".": TokenTypes.index("enumMember"),
                                    },
                                },
                                "create": {
                                    "type": TokenTypes.index("parameter"),
                                    "type_map": {
                                        ".": TokenTypes.index("number"),
                                    },
                                },
                                "update": {
                                    "type": TokenTypes.index("parameter"),
                                    "type_map": {
                                        ".": TokenTypes.index("enumMember"),
                                    },
                                },
                                "delete": {
                                    "type": TokenTypes.index("parameter"),
                                    "type_map": {
                                        ".": TokenTypes.index("enumMember"),
                                    },
                                },
                            },
                        },
                    },
                },
                "inputValidators": {
                    "type": TokenTypes.index("keyword"),
                    "type_map": {
                        "type": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("class"),
                            },
                        },
                        "message": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("string"),
                            },
                        },
                        "test": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("string"),
                            },
                        },
                    },
                },
            },
        },
    },
    "Workflow": {
        "spec": {
            "type": TokenTypes.index("keyword"),
            "type_map": {
                "crdRef": {
                    "type": TokenTypes.index("typeParameter"),
                    "type_map": {
                        "apiGroup": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("namespace"),
                            },
                        },
                        "version": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("string"),
                            },
                        },
                        "kind": {
                            "type": TokenTypes.index("parameter"),
                            "type_map": {
                                ".": TokenTypes.index("class"),
                            },
                        },
                    },
                },
                "steps": {
                    "type": TokenTypes.index("keyword"),
                    "type_map": {
                        "label": {
                            "type": TokenTypes.index("property"),
                            "type_map": {
                                ".": TokenTypes.index("string"),
                            },
                        },
                        "functionRef": {
                            "type": TokenTypes.index("property"),
                            "type_map": {
                                "name": {
                                    "type": TokenTypes.index("property"),
                                    "type_map": {
                                        ".": TokenTypes.index("function"),
                                    },
                                },
                            },
                        },
                        "inputs": {
                            "type": TokenTypes.index("property"),
                            "type_map": {
                                ".": {
                                    "type": TokenTypes.index("argument"),
                                    "type_map": {
                                        ".": TokenTypes.index("argument"),
                                    },
                                }
                            },
                        },
                    },
                },
            },
        }
    },
}


class IndexingLoader(SafeLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._semantic_tokens = []
        self.last_token_start = (0, 0)

    def construct_document(self, node):
        doc = super().construct_document(node)

        field_type_hint_maps = SEMANTIC_TYPE_STRUCTURE.get(doc.get("kind"), {})

        self._semantic_tokens = []
        self.extract_semantic_structure_info(node, field_type_hint_maps)
        doc[_SEMANTIC_TOKENS_KEY] = self._semantic_tokens

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

    def extract_semantic_token_info(self, node, type_hint, type_hint_map):
        if isinstance(node, (MappingNode, SequenceNode)):
            self.extract_semantic_structure_info(node, type_hint_map)
            return

        if type_hint:
            node_type = type_hint
        else:
            tag_kind = node.tag.rsplit(":", 1)[-1]
            if tag_kind in {"int", "float", "bool"}:
                node_type = TokenTypes.index("number")
            else:
                node_type = TokenTypes.index("string")

        last_line, last_column = self.last_token_start

        node_line = node.start_mark.line
        node_column = node.start_mark.column

        self._semantic_tokens.extend(
            [
                node_line - last_line,
                node_column - (0 if node_line > last_line else last_column),
                len(node.value),
                node_type,
                0,
            ]
        )


        self.last_token_start = (node_line, node_column)
        return

    def extract_semantic_structure_info(self, node, type_hint_map):
        if isinstance(node, MappingNode):
            for key, value in node.value:
                hints = type_hint_map.get(key.value, {})

                self.extract_semantic_token_info(
                    key,
                    type_hint=hints.get("type", TokenTypes.index("keyword")),
                    type_hint_map={},
                )
                self.extract_semantic_structure_info(
                    value, type_hint_map=hints.get("type_map", {})
                )

            return

        if isinstance(node, SequenceNode):
            for value in node.value:
                self.extract_semantic_structure_info(value, type_hint_map=type_hint_map)
            return

        self.extract_semantic_token_info(
            node, type_hint=type_hint_map.get("."), type_hint_map=type_hint_map
        )


STRIP_KEYS = set([_RANGE_KEY, _SEMANTIC_TOKENS_KEY, _SEMANTIC_TOKEN_VERBOSE_KEY])


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
