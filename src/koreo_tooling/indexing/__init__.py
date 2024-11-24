from __future__ import annotations
from typing import Any

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode

from lsprotocol import types

from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE, VALUE
from .semantics import (
    Modifier,
    NodeInfo,
    RelativePosition,
    SemanticStructure,
    TokenModifiers,
    TokenType,
    TokenTypes,
    TypeIndex,
    to_lsp_semantics,
)

from . import cel_semantics

_RANGE_KEY = "..range.."
_STRUCTURE_KEY = "..structure.."


class IndexingLoader(SafeLoader):
    def __init__(self, *args, doc, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_doc_start = (0, 0)
        self.doc = doc

    def construct_document(self, node):
        doc = super().construct_document(node)

        doc_kind = doc.get("kind")
        doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(doc_kind)
        if not doc_semantics:
            doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(ALL, {})

        structure, doc_last_pos = extract_semantic_structure_info(
            key_path="",
            last_token_abs_start=self.last_doc_start,
            last_node_end_mark=None,
            node=node,
            type_hint_map=doc_semantics,
            doc=self.doc,
        )
        doc[_STRUCTURE_KEY] = structure
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
    last_node_end_mark,
    node,
    type_hint_map: dict[str, SemanticStructure],
    doc,
):
    semantic_nodes = []
    if last_node_end_mark:
        if last_node_end_mark.line < node.start_mark.line - 1:
            for line_offset in range(node.start_mark.line - last_node_end_mark.line):
                line_data = doc.lines[last_node_end_mark.line + line_offset]
                semantic_nodes.append(
                    NodeInfo(
                        key=key_path,
                        position=RelativePosition(
                            node_line=line_offset,
                            offset=0,
                            length=len(line_data),
                        ),
                        node_type="comment",
                    )
                )

    if isinstance(node, MappingNode):
        new_last_start = last_token_abs_start
        for key, value in node.value:
            hints = type_hint_map.get(key.value, {})
            if not hints:
                hints = type_hint_map.get(ALL, {})

            key_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}._{key.value}_",
                last_token_abs_start=new_last_start,
                last_node_end_mark=last_node_end_mark,
                node=key,
                type_hint=hints.get("type", "keyword"),
                modifier=hints.get("modifier", []),
                type_hint_map={},
                doc=doc,
            )
            semantic_nodes.extend(key_semantic_nodes)

            sub_structure = hints.get("sub_structure", {})
            value_semantic_info = sub_structure.get(VALUE, {})

            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}.{key.value}",
                last_token_abs_start=new_last_start,
                last_node_end_mark=last_node_end_mark,
                node=value,
                type_hint=value_semantic_info.get("type"),
                modifier=value_semantic_info.get("modifier", []),
                type_hint_map=sub_structure,
                doc=doc,
            )
            semantic_nodes.extend(value_semantic_nodes)

        return semantic_nodes, new_last_start

    if isinstance(node, SequenceNode):
        new_last_start = last_token_abs_start
        for idx, value in enumerate(node.value):
            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                key_path=f"{key_path}.{idx}",
                last_token_abs_start=new_last_start,
                last_node_end_mark=last_node_end_mark,
                node=value,
                type_hint=None,
                modifier=[],
                type_hint_map=type_hint_map,
                doc=doc,
            )
            semantic_nodes.extend(value_semantic_nodes)
        return semantic_nodes, new_last_start

    value_semantic_info = type_hint_map.get(VALUE, {})

    value_semantic_nodes, new_last_start = _extract_value_semantic_info(
        key_path=key_path,
        last_token_abs_start=last_token_abs_start,
        last_node_end_mark=last_node_end_mark,
        node=node,
        type_hint=value_semantic_info.get("type"),
        modifier=value_semantic_info.get("modifier", []),
        type_hint_map=type_hint_map,
        doc=doc,
    )
    semantic_nodes.extend(value_semantic_nodes)
    return semantic_nodes, new_last_start


def _extract_value_semantic_info(
    key_path: str,
    last_token_abs_start: tuple[int, int],
    last_node_end_mark,
    node,
    type_hint: TokenType | None,
    modifier: list[Modifier],
    type_hint_map: dict[str, SemanticStructure],
    doc,
):
    if isinstance(node, (MappingNode, SequenceNode)):
        return extract_semantic_structure_info(
            key_path=key_path,
            last_token_abs_start=last_token_abs_start,
            last_node_end_mark=last_node_end_mark,
            node=node,
            type_hint_map=type_hint_map,
            doc=doc,
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

    char_offset = node_column - (0 if node_line > last_line else last_column)

    if node_type == "string" and node.value.startswith("="):
        if node_line == node.end_mark.line:
            cel_nodes = cel_semantics.parse(
                cel_expression=node.value, seed_line=0, seed_offset=char_offset
            )
            return (cel_nodes, (node_line, node_column))

        nodes = [
            NodeInfo(
                key=key_path,
                position=RelativePosition(
                    node_line=node_line - last_line,
                    offset=char_offset,
                    length=1,
                ),
                node_type="operator",
            )
        ]

        cel_lines = doc.lines[node_line + 1 : node.end_mark.line]

        nodes.extend(
            cel_semantics.parse(
                cel_expression="\n".join(cel_lines),
                seed_line=1,
                seed_offset=0,
            )
        )

        return (nodes, (node_line + len(cel_lines), 0))

    if node_line == node.end_mark.line:
        value_len = node.end_mark.column - node_column
    else:
        line_data = doc.lines[node_line]
        value_len = len(line_data) - node_column

    # if key_path == ".spec.materializers.base.spec.two":
    #     raise Exception(f"<{len(node_value_lines)}: {node_value_lines}>")
    # raise Exception(
    #    f"<{node.start_mark.line}:{node.start_mark.column}>{len(node.value)}<{node.end_mark.line}:{node.end_mark.column}>"
    # )

    nodes = []
    while True:
        nodes.append(
            NodeInfo(
                key=key_path,
                position=RelativePosition(
                    node_line=node_line - last_line,
                    offset=char_offset,
                    length=value_len,
                ),
                node_type=node_type,
            )
        )

        if node_line + 1 >= node.end_mark.line:
            break

        last_line = node_line
        last_column = node_column

        node_line += 1
        node_column = 0

        line_data = doc.lines[node_line]
        char_offset = len(line_data) - len(line_data.lstrip())
        value_len = len(line_data.strip())

    return (
        nodes,
        (node_line, node_column),
    )


STRIP_KEYS = set([_RANGE_KEY])


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
