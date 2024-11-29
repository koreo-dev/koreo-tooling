from __future__ import annotations
from typing import Any

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode

from lsprotocol import types

from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE, VALUE
from .semantics import (
    SemanticAnchor,
    Modifier,
    NodeDiagnostic,
    SemanticNode,
    Position,
    SemanticStructure,
    Severity,
    TokenModifiers,
    TokenType,
    TokenTypes,
    TypeIndex,
    extract_diagnostics,
    flatten,
    to_lsp_semantics,
)

from . import cel_semantics

_RANGE_KEY = "..range.."
_STRUCTURE_KEY = "..structure.."


class IndexingLoader(SafeLoader):
    def __init__(self, *args, doc, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_node_abs_start = (0, 0)
        self.last_node_abs_end = (0, 0)
        self.doc = doc
        self.doc_count = 0

    def construct_document(self, node):
        yaml_doc = super().construct_document(node)

        doc_kind = yaml_doc.get("kind")
        doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(doc_kind)
        if not doc_semantics:
            doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(ALL, {})

        doc_metadata = yaml_doc.get("metadata", {})
        doc_name = doc_metadata.get("name")

        if not doc_kind:
            anchor_key = f"Unknown:{self.doc_count}"
        elif doc_kind and doc_name:
            anchor_key = f"{doc_kind}:{doc_name}"
        else:
            anchor_key = f"{doc_kind}:{self.doc_count}"

        anchor_abs_start = Position(
            line=node.start_mark.line,
            offset=node.start_mark.column,
        )

        last_line, last_col = self.last_node_abs_start

        anchor_rel_start = Position(
            line=node.start_mark.line - last_line,
            offset=0 if node.start_mark.line >= last_line else last_col,
        )

        structure, last_abs_start = extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
            key_path="",
            last_token_abs_start=self.last_node_abs_start,
            yaml_node=node,
            type_hint_map=doc_semantics,
            doc=self.doc,
        )
        yaml_doc[_STRUCTURE_KEY] = SemanticAnchor(
            key=anchor_key,
            abs_position=anchor_abs_start,
            rel_position=anchor_rel_start,
            children=structure,
        )

        self.last_node_abs_start = last_abs_start

        self.doc_count = self.doc_count + 1

        return yaml_doc

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
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    key_path: str,
    yaml_node,
    doc,
    type_hint_map: dict[str, SemanticStructure],
):
    semantic_nodes = []

    if isinstance(yaml_node, MappingNode):
        new_last_start = last_token_abs_start
        seen_keys = set[str]()
        for key, value in yaml_node.value:
            hints = type_hint_map.get(key.value, {})
            if not hints:
                hints = type_hint_map.get(ALL, {})

            node_diagnostic = None
            if f"{key.value}" in seen_keys:
                node_diagnostic = NodeDiagnostic(
                    message="Duplicate key", severity=Severity.error
                )

            key_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                key_path=f"{key_path}._{key.value}_",
                yaml_node=key,
                type_hint=hints.get("type", "keyword"),
                modifier=hints.get("modifier", []),
                type_hint_map={},
                doc=doc,
                diagnostic=node_diagnostic,
            )
            semantic_nodes.extend(key_semantic_nodes)
            seen_keys.add(f"{key.value}")

            sub_structure = hints.get("sub_structure", {})
            value_semantic_info = sub_structure.get(VALUE, {})

            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                key_path=f"{key_path}.{key.value}",
                yaml_node=value,
                type_hint=value_semantic_info.get("type"),
                modifier=value_semantic_info.get("modifier", []),
                type_hint_map=sub_structure,
                doc=doc,
            )
            semantic_nodes.extend(value_semantic_nodes)

        return semantic_nodes, new_last_start

    if isinstance(yaml_node, SequenceNode):
        new_last_start = last_token_abs_start
        for idx, value in enumerate(yaml_node.value):
            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                key_path=f"{key_path}.{idx}",
                yaml_node=value,
                type_hint=None,
                modifier=[],
                type_hint_map=type_hint_map,
                doc=doc,
            )
            semantic_nodes.extend(value_semantic_nodes)
        return semantic_nodes, new_last_start

    value_semantic_info = type_hint_map.get(VALUE, {})

    value_semantic_nodes, new_last_start = _extract_value_semantic_info(
        anchor_abs_start=anchor_abs_start,
        last_token_abs_start=last_token_abs_start,
        key_path=key_path,
        yaml_node=yaml_node,
        type_hint=value_semantic_info.get("type"),
        modifier=value_semantic_info.get("modifier", []),
        type_hint_map=type_hint_map,
        doc=doc,
    )
    semantic_nodes.extend(value_semantic_nodes)
    return semantic_nodes, new_last_start


def _extract_value_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    key_path: str,
    yaml_node,
    type_hint: TokenType | None,
    modifier: list[Modifier],
    type_hint_map: dict[str, SemanticStructure],
    doc,
    diagnostic: NodeDiagnostic | None = None,
):
    if isinstance(yaml_node, (MappingNode, SequenceNode)):
        return extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            key_path=key_path,
            yaml_node=yaml_node,
            doc=doc,
            type_hint_map=type_hint_map,
        )

    if type_hint:
        node_type = type_hint
    else:
        tag_kind = yaml_node.tag.rsplit(":", 1)[-1]
        if tag_kind in {"int", "float", "bool"}:
            node_type = "number"
        else:
            node_type = "string"

    last_line, last_column = last_token_abs_start

    node_line = yaml_node.start_mark.line
    node_column = yaml_node.start_mark.column

    if node_type == "string" and yaml_node.value.startswith("="):
        if node_line == yaml_node.end_mark.line:
            line_data = doc.lines[node_line]
            line_len = len(line_data)

            # This is to address lines that are quoted.
            # The quotes throw off the column position, but are not represented
            # in the value.
            eq_char_offset = yaml_node.start_mark.column
            while True:
                if line_data[eq_char_offset] == "=":
                    break

                if eq_char_offset >= line_len:
                    break

                eq_char_offset += 1

            char_offset = eq_char_offset - (0 if node_line > last_line else last_column)

            cel_nodes = cel_semantics.parse(
                cel_expression=[yaml_node.value],
                anchor_base_pos=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                seed_line=0,
                seed_offset=char_offset,
                abs_offset=eq_char_offset - char_offset,
            )
            return (cel_nodes, (node_line, node_column))

        nodes = [
                key=key_path,
            SemanticNode(
                position=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=last_token_abs_start
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                length=1,
                node_type="operator",
                modifier=modifier,
                diagnostic=diagnostic,
            )
        ]

        cel_nodes = cel_semantics.parse(
            cel_expression=doc.lines[node_line + 1 : yaml_node.end_mark.line],
            anchor_base_pos=_compute_rel_position(
                line=node_line, offset=node_column, relative_to=anchor_abs_start
            ),
            seed_line=1,
            seed_offset=0,
        )
        nodes.extend(cel_nodes)

        # TODO: Just compute directly from anchor_rel position.
        last_node_line = node_line
        last_node_col = 0
        for yaml_node in cel_nodes:
            if yaml_node.position.line == 0:
                last_node_col = yaml_node.position.offset
            else:
                last_node_col = 0

            last_node_line += yaml_node.position.line

        return (nodes, (last_node_line, last_node_col))

    if node_line == yaml_node.end_mark.line:
        value_len = yaml_node.end_mark.column - node_column
    else:
        line_data = doc.lines[node_line]
        value_len = len(line_data) - node_column

    # if key_path == ".spec.materializers.base.spec.two":
    #     raise Exception(f"<{len(node_value_lines)}: {node_value_lines}>")
    # raise Exception(
    # )

    char_offset = node_column - (0 if node_line > last_line else last_column)

    nodes = []
    while True:
        nodes.append(
                key=key_path,
            SemanticNode(
                position=Position(
                    line=node_line - last_line,
                    offset=char_offset,
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, offset=char_offset, relative_to=anchor_abs_start
                ),
                length=value_len,
                node_type=node_type,
                modifier=modifier,
                diagnostic=diagnostic,
            )
        )

        if node_line + 1 >= yaml_node.end_mark.line:
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


def _compute_rel_position(line: int, offset: int, relative_to: Position) -> Position:
    rel_to_line, rel_to_offset = relative_to
    rel_line = line - rel_to_line
    return Position(
        line=rel_line, offset=offset if line == 0 else (offset - rel_to_offset)
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
