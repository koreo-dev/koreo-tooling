from __future__ import annotations
from typing import Any, Sequence

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode

from lsprotocol import types

from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE, VALUE
from .semantics import (
    IndexFn,
    Modifier,
    NodeDiagnostic,
    Position,
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    SemanticStructure,
    Severity,
    TokenModifiers,
    TokenType,
    TokenTypes,
    compute_abs_range,
    extract_diagnostics,
    flatten,
    generate_key_range_index,
    to_lsp_semantics,
    anchor_path_search,
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

        last_line, _ = self.last_node_abs_start

        anchor_rel_start = Position(
            line=node.start_mark.line - last_line,
            offset=node.start_mark.column,
        )

        structure, last_abs_start = extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
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
    yaml_node,
    doc,
    type_hint_map: dict[str, SemanticStructure],
) -> tuple[list[SemanticNode], Position]:
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
            else:
                seen_keys.add(f"{key.value}")

            key_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                path_key=f"{key.value}",
                yaml_node=key,
                doc=doc,
                path_key_fn=hints.get("path_key_fn"),
                index_key_fn=hints.get("index_key_fn"),
                type_hint=hints.get("type", "keyword"),
                modifier=hints.get("modifier"),
                type_hint_map={},
                diagnostic=node_diagnostic,
            )

            # This should never happen, in any case I am aware of.
            if len(key_semantic_nodes) != 1:
                raise Exception(f"More than one key node! {key_semantic_nodes}")

            key_semantic_node = key_semantic_nodes.pop()

            sub_structure = hints.get("sub_structure", {})
            value_semantic_info = sub_structure.get(VALUE, {})

            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                yaml_node=value,
                doc=doc,
                path_key_fn=value_semantic_info.get("path_key_fn"),
                index_key_fn=value_semantic_info.get("index_key_fn"),
                type_hint=value_semantic_info.get("type"),
                modifier=value_semantic_info.get("modifier", []),
                type_hint_map=sub_structure,
            )
            key_semantic_node = key_semantic_node._replace(
                children=value_semantic_nodes
            )
            semantic_nodes.append(key_semantic_node)

        return semantic_nodes, new_last_start

    if isinstance(yaml_node, SequenceNode):
        new_last_start = last_token_abs_start

        value_semantic_info = type_hint_map.get(VALUE, {})

        for value in yaml_node.value:
            path_key_fn = value_semantic_info.get("path_key_fn")
            if path_key_fn:
                path_key = path_key_fn(value=value.value)
            else:
                path_key = None

            index_key_fn = value_semantic_info.get("index_key_fn")
            if index_key_fn:
                index_key = index_key_fn(value=value.value)
            else:
                index_key = None

            value_semantic_nodes, new_last_start = _extract_value_semantic_info(
                anchor_abs_start=anchor_abs_start,
                last_token_abs_start=new_last_start,
                yaml_node=value,
                doc=doc,
                path_key=path_key,
                index_key_fn=value_semantic_info.get("index_key_fn"),
                type_hint=value_semantic_info.get("type"),
                modifier=value_semantic_info.get("modifier", []),
                type_hint_map=value_semantic_info.get("sub_structure", {}),
            )
            semantic_nodes.extend(value_semantic_nodes)
        return semantic_nodes, new_last_start

    value_semantic_info = type_hint_map.get(VALUE, {})

    value_semantic_nodes, new_last_start = _extract_value_semantic_info(
        anchor_abs_start=anchor_abs_start,
        last_token_abs_start=last_token_abs_start,
        yaml_node=yaml_node,
        doc=doc,
        path_key_fn=value_semantic_info.get("path_key_fn"),
        index_key_fn=value_semantic_info.get("index_key_fn"),
        type_hint=value_semantic_info.get("type"),
        modifier=value_semantic_info.get("modifier"),
        type_hint_map=type_hint_map,
    )
    semantic_nodes.extend(value_semantic_nodes)
    return semantic_nodes, new_last_start


def _extract_value_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    path_key: str | None = None,
    path_key_fn: IndexFn | None = None,
    index_key: str | None = None,
    index_key_fn: IndexFn | None = None,
    type_hint: TokenType | None = None,
    modifier: list[Modifier] | None = None,
    type_hint_map: dict[str, SemanticStructure] | None = None,
    diagnostic: NodeDiagnostic | None = None,
) -> tuple[Sequence[SemanticBlock | SemanticNode], Position]:
    if isinstance(yaml_node, (MappingNode, SequenceNode)):
        nodes, last_token_pos = extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            type_hint_map=type_hint_map if type_hint_map is not None else {},
        )

        if not (path_key or index_key):
            return nodes, last_token_pos

        else:
            block = [
                SemanticBlock(
                    path_key=path_key,
                    index_key=index_key,
                    anchor_rel_start=_compute_rel_position(
                        line=yaml_node.start_mark.line,
                        offset=yaml_node.start_mark.column,
                        relative_to=anchor_abs_start,
                    ),
                    anchor_rel_end=_compute_rel_position(
                        line=yaml_node.end_mark.line,
                        offset=yaml_node.end_mark.column,
                        relative_to=anchor_abs_start,
                    ),
                    children=nodes,
                )
            ]
            return block, last_token_pos

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
            return (cel_nodes, Position(line=node_line, offset=node_column))

        nodes = [
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

        return (nodes, Position(line=last_node_line, offset=last_node_col))

    if node_line == yaml_node.end_mark.line:
        value_len = yaml_node.end_mark.column - node_column
    else:
        line_data = doc.lines[node_line]
        value_len = len(line_data) - node_column

    char_offset = node_column - (0 if node_line > last_line else last_column)

    if path_key_fn:
        path_key = path_key_fn(value=yaml_node.value)

    if index_key_fn:
        index_key = index_key_fn(value=yaml_node.value)

    nodes = []
    while True:
        nodes.append(
            SemanticNode(
                path_key=path_key,
                index_key=index_key,
                position=Position(
                    line=node_line - last_line,
                    offset=char_offset,
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
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
        Position(line=node_line, offset=node_column),
    )


def _compute_rel_position(line: int, offset: int, relative_to: Position) -> Position:
    rel_to_line, rel_to_offset = relative_to
    rel_line = line - rel_to_line
    return Position(
        line=rel_line, offset=offset if rel_line > 0 else (offset - rel_to_offset)
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
