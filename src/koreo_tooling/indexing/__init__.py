from __future__ import annotations
from typing import Sequence

from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, SequenceNode


from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE
from .semantics import (
    Modifier,
    NodeDiagnostic,
    Position,
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    SemanticStructure,
    Severity,
    TokenModifiers,
    TokenTypes,
    anchor_local_key_search,
    compute_abs_position,
    compute_abs_range,
    extract_diagnostics,
    flatten,
    generate_key_range_index,
    to_lsp_semantics,
)

from . import cel_semantics

_STRUCTURE_KEY = "..structure.."


class IndexingLoader(SafeLoader):
    def __init__(self, *args, doc, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_node_abs_start = Position(0, 0)
        self.last_node_abs_end = Position(0, 0)
        self.doc = doc
        self.doc_count = 0

    def construct_document(self, node):
        yaml_doc = super().construct_document(node)

        doc_kind = yaml_doc.get("kind")
        doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(doc_kind)
        if not doc_semantics:
            doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(ALL, SemanticStructure())

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
            doc=self.doc,
            semantic_type=doc_semantics,
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


def extract_semantic_structure_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
) -> tuple[Sequence[SemanticBlock | SemanticNode], Position]:
    match semantic_type:
        case SemanticStructure():
            clean_semantic_type = semantic_type
        case None:
            clean_semantic_type = SemanticStructure()
        case _:
            clean_semantic_type = SemanticStructure(sub_structure=semantic_type)

    if isinstance(yaml_node, MappingNode):
        return _extract_map_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            semantic_type=clean_semantic_type.sub_structure,
        )

    if isinstance(yaml_node, SequenceNode):
        return _extract_list_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            semantic_type=clean_semantic_type.sub_structure,
        )

    return _extract_value_semantic_info(
        anchor_abs_start=anchor_abs_start,
        last_token_abs_start=last_token_abs_start,
        yaml_node=yaml_node,
        doc=doc,
        semantic_type=clean_semantic_type,
    )


def _extract_map_structure_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
) -> tuple[list[SemanticNode], Position]:
    semantic_nodes = []
    new_last_start = last_token_abs_start
    seen_keys = set[str]()

    semantic_type_map: dict[str, SemanticStructure] = {}
    if isinstance(semantic_type, dict):
        semantic_type_map = semantic_type
    elif semantic_type:
        semantic_type_map = {ALL: semantic_type}

    for key, value in yaml_node.value:
        node_diagnostic = None
        if f"{key.value}" in seen_keys:
            node_diagnostic = NodeDiagnostic(
                message="Duplicate key", severity=Severity.error
            )
        else:
            seen_keys.add(f"{key.value}")

        key_semantic_type = semantic_type_map.get(key.value)
        if not key_semantic_type:
            key_semantic_type = semantic_type_map.get(ALL, SemanticStructure())

        if not key_semantic_type.type:
            key_semantic_type.type = "keyword"

        key_semantic_nodes, new_last_start = _extract_value_semantic_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=new_last_start,
            yaml_node=key,
            doc=doc,
            semantic_type=key_semantic_type,
            diagnostic=node_diagnostic,
        )

        # This should never happen, in any case I am aware of.
        if len(key_semantic_nodes) != 1:
            raise Exception(f"More than one key node! {key_semantic_nodes}")

        value_semantic_nodes, new_last_start = _extract_value_semantic_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=new_last_start,
            yaml_node=value,
            doc=doc,
            semantic_type=key_semantic_type.sub_structure,
        )

        key_semantic_node = key_semantic_nodes[-1]
        semantic_nodes.append(key_semantic_node._replace(children=value_semantic_nodes))

    return semantic_nodes, new_last_start


def _extract_list_structure_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
) -> tuple[list[SemanticNode], Position]:
    semantic_nodes = []
    new_last_start = last_token_abs_start

    if isinstance(semantic_type, SemanticStructure):
        item_semantic_type = semantic_type
    else:
        item_semantic_type = SemanticStructure(sub_structure=semantic_type)

    for value in yaml_node.value:
        value_semantic_nodes, new_last_start = _extract_value_semantic_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=new_last_start,
            yaml_node=value,
            doc=doc,
            semantic_type=item_semantic_type,
        )
        semantic_nodes.extend(value_semantic_nodes)

    return semantic_nodes, new_last_start


def _extract_cel_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    modifier: list[Modifier] | None = None,
    diagnostic: NodeDiagnostic | None = None,
):
    node_line = yaml_node.start_mark.line
    node_column = yaml_node.start_mark.column
    last_line, last_column = last_token_abs_start

    nodes = []

    if node_line == yaml_node.end_mark.line:
        # Single line expression.

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

        nodes.extend(
            cel_semantics.parse(
                cel_expression=[yaml_node.value],
                anchor_base_pos=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                seed_line=0,
                seed_offset=char_offset,
                abs_offset=eq_char_offset - char_offset,
            )
        )
        # return (cel_nodes, Position(line=node_line, offset=node_column))
    else:
        # Multiline expression

        # The multiline indicator character
        line_data = doc.lines[node_line]
        line_len = len(line_data)
        nodes.append(
            SemanticNode(
                position=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=last_token_abs_start
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                length=line_len - node_column,
                node_type="operator",
                modifier=modifier,
                diagnostic=diagnostic,
            )
        )

        nodes.extend(
            cel_semantics.parse(
                cel_expression=doc.lines[node_line + 1 : yaml_node.end_mark.line],
                anchor_base_pos=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                seed_line=1,
                seed_offset=0,
            )
        )

    # Go to the deepest node
    last_node = nodes[-1]
    if last_node:
        while True:
            if not last_node.children:
                break

            last_node = last_node.children[-1]

    last_abs_position = Position(
        line=last_node.anchor_rel.line + anchor_abs_start.line,
        offset=last_node.anchor_rel.offset,
    )

    block = [
        SemanticBlock(
            local_key=None,
            index_key=None,
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

    return (block, last_abs_position)


def _extract_scalar_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    semantic_type: SemanticStructure,
    diagnostic: NodeDiagnostic | None = None,
):
    last_line, last_column = last_token_abs_start

    node_line = yaml_node.start_mark.line
    node_column = yaml_node.start_mark.column

    if node_line == yaml_node.end_mark.line:
        value_len = yaml_node.end_mark.column - node_column
    else:
        line_data = doc.lines[node_line]
        value_len = len(line_data) - node_column

    char_offset = node_column - (0 if node_line > last_line else last_column)

    if semantic_type.local_key_fn:
        local_key = semantic_type.local_key_fn(value=yaml_node.value)
    else:
        local_key = None

    if semantic_type.index_key_fn:
        index_key = semantic_type.index_key_fn(value=yaml_node.value)
    else:
        index_key = None

    nodes = []
    while True:
        nodes.append(
            SemanticNode(
                local_key=local_key,
                index_key=index_key,
                position=Position(
                    line=node_line - last_line,
                    offset=char_offset,
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, offset=node_column, relative_to=anchor_abs_start
                ),
                length=value_len,
                node_type=semantic_type.type,
                modifier=semantic_type.modifier,
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

    last_token_pos = Position(line=node_line, offset=node_column)

    if len(nodes) <= 1:
        return (
            nodes,
            last_token_pos,
        )

    block = [
        SemanticBlock(
            local_key=local_key,
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
    return (block, last_token_pos)


def _extract_value_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
    diagnostic: NodeDiagnostic | None = None,
) -> tuple[Sequence[SemanticBlock | SemanticNode], Position]:
    match semantic_type:
        case SemanticStructure():
            clean_semantic_type = semantic_type
        case _:
            clean_semantic_type = SemanticStructure()

    if isinstance(yaml_node, (MappingNode, SequenceNode)):
        nodes, last_token_pos = extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            semantic_type=semantic_type,
        )

        if not (clean_semantic_type.local_key_fn or clean_semantic_type.index_key_fn):
            return nodes, last_token_pos

        if clean_semantic_type.local_key_fn:
            local_key = clean_semantic_type.local_key_fn(value=yaml_node.value)
        else:
            local_key = None

        if clean_semantic_type.index_key_fn:
            index_key = clean_semantic_type.index_key_fn(value=yaml_node.value)
        else:
            index_key = None

        block = [
            SemanticBlock(
                local_key=local_key,
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

    if clean_semantic_type.type:
        node_type = clean_semantic_type.type
    else:
        tag_kind = yaml_node.tag.rsplit(":", 1)[-1]
        if tag_kind in {"int", "float", "bool"}:
            node_type = "number"
        else:
            node_type = "string"

    if node_type == "string" and yaml_node.value.startswith("="):
        return _extract_cel_semantic_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            modifier=clean_semantic_type.modifier,
            diagnostic=diagnostic,
        )

    clean_semantic_type.type = node_type

    return _extract_scalar_semantic_info(
        anchor_abs_start=anchor_abs_start,
        last_token_abs_start=last_token_abs_start,
        yaml_node=yaml_node,
        doc=doc,
        semantic_type=clean_semantic_type,
        diagnostic=diagnostic,
    )


def _compute_rel_position(line: int, offset: int, relative_to: Position) -> Position:
    rel_to_line, rel_to_offset = relative_to
    rel_line = line - rel_to_line
    return Position(
        line=rel_line, offset=offset if rel_line > 0 else (offset - rel_to_offset)
    )
