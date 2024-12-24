from typing import Sequence
import copy

from yaml.nodes import Node, MappingNode, SequenceNode


from .koreo_semantics import ALL
from .semantics import (
    FieldIndexFn,
    Modifier,
    NodeDiagnostic,
    Position,
    Range,
    SemanticBlock,
    SemanticNode,
    SemanticStructure,
    Severity,
    compute_abs_position,
)

from . import cel_semantics


def extract_semantic_structure_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node: Node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
) -> tuple[Sequence[SemanticBlock | SemanticNode], Position]:
    match semantic_type:
        case SemanticStructure():
            clean_semantic_type = semantic_type
        case None:
            clean_semantic_type = SemanticStructure()
        case dict():
            clean_semantic_type = SemanticStructure(sub_structure=semantic_type)

    if isinstance(yaml_node, MappingNode):
        return _extract_map_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=last_token_abs_start,
            yaml_node=yaml_node,
            doc=doc,
            semantic_type=clean_semantic_type.sub_structure,
            strict_sub_structure_keys=clean_semantic_type.strict_sub_structure_keys,
            field_index_key_fn=clean_semantic_type.field_index_key_fn,
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
    yaml_node: Node,
    doc,
    semantic_type: dict[str, SemanticStructure] | SemanticStructure | None,
    strict_sub_structure_keys: bool = False,
    field_index_key_fn: FieldIndexFn | None = None,
) -> tuple[list[SemanticNode], Position]:
    semantic_nodes = []
    new_last_start = last_token_abs_start
    seen_keys = set[str]()

    semantic_type_map: dict[str, SemanticStructure] = {}
    if isinstance(semantic_type, dict):
        semantic_type_map = semantic_type
    elif semantic_type:
        semantic_type_map = {ALL: semantic_type}

    if field_index_key_fn and (index := field_index_key_fn(value=yaml_node.value)):
        sub_index_field, sub_index_value = index
    else:
        sub_index_field = None
        sub_index_value = None

    for key, value in yaml_node.value:
        node_diagnostic = None
        if f"{key.value}" in seen_keys:
            node_diagnostic = NodeDiagnostic(
                message="Duplicate key", severity=Severity.error
            )
        else:
            seen_keys.add(f"{key.value}")

        if (
            strict_sub_structure_keys
            and not node_diagnostic
            and f"{key.value}" not in semantic_type_map
        ):
            node_diagnostic = NodeDiagnostic(
                message="Unknown key", severity=Severity.error
            )

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

        match key_semantic_type.sub_structure:
            case SemanticStructure():
                value_semantic_type = key_semantic_type.sub_structure
            case None:
                value_semantic_type = SemanticStructure(
                    strict_sub_structure_keys=key_semantic_type.strict_sub_structure_keys
                )
            case dict():
                value_semantic_type = SemanticStructure(
                    sub_structure=key_semantic_type.sub_structure,
                    strict_sub_structure_keys=key_semantic_type.strict_sub_structure_keys,
                )

        if (
            sub_index_field
            and sub_index_field == key.value
            and not value_semantic_type.index_key_fn
        ):
            value_semantic_type = copy.replace(
                value_semantic_type, index_key_fn=lambda value: sub_index_value
            )

        value_semantic_nodes, new_last_start = _extract_value_semantic_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=new_last_start,
            yaml_node=value,
            doc=doc,
            semantic_type=value_semantic_type,
        )

        key_semantic_node = key_semantic_nodes[-1]
        semantic_nodes.append(key_semantic_node._replace(children=value_semantic_nodes))

    return semantic_nodes, new_last_start


def _extract_list_structure_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node: Node,
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
    yaml_node: Node,
    doc,
    modifier: list[Modifier] | None = None,
    diagnostic: NodeDiagnostic | None = None,
):
    last_line = last_token_abs_start.line
    last_column = last_token_abs_start.character

    node_line = yaml_node.start_mark.line
    node_column = yaml_node.start_mark.column

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

        seed_line = node_line - last_line
        char_offset = eq_char_offset - (0 if node_line > last_line else last_column)

        nodes.extend(
            cel_semantics.parse(
                cel_expression=[yaml_node.value],
                anchor_base_pos=_compute_rel_position(
                    line=node_line - seed_line,
                    character=node_column,
                    relative_to=anchor_abs_start,
                ),
                seed_line=seed_line,
                seed_offset=char_offset,
                abs_offset=eq_char_offset - char_offset,
            )
        )
    else:
        # Multiline expression

        # The multiline indicator character
        line_data = doc.lines[node_line]
        line_len = len(line_data)
        nodes.append(
            SemanticNode(
                position=_compute_rel_position(
                    line=node_line,
                    character=node_column,
                    relative_to=last_token_abs_start,
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line, character=node_column, relative_to=anchor_abs_start
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
                    line=node_line, character=node_column, relative_to=anchor_abs_start
                ),
                seed_line=1,
                seed_offset=0,
            )
        )

    # Go to the deepest node
    last_node = nodes[-1]
    while last_node and last_node.children:
        last_node = last_node.children[-1]

    last_abs_position = compute_abs_position(
        rel_position=last_node.anchor_rel, abs_position=anchor_abs_start
    )

    block = [
        SemanticBlock(
            local_key=None,
            index_key=None,
            anchor_rel=Range(
                start=_compute_rel_position(
                    line=yaml_node.start_mark.line,
                    character=yaml_node.start_mark.column,
                    relative_to=anchor_abs_start,
                ),
                end=_compute_rel_position(
                    line=yaml_node.end_mark.line,
                    character=yaml_node.end_mark.column,
                    relative_to=anchor_abs_start,
                ),
            ),
            children=nodes,
        )
    ]

    return (block, last_abs_position)


def _extract_scalar_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node: Node,
    doc,
    semantic_type: SemanticStructure,
    diagnostic: NodeDiagnostic | None = None,
):
    last_line = last_token_abs_start.line
    last_column = last_token_abs_start.character

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
                    character=char_offset,
                ),
                anchor_rel=_compute_rel_position(
                    line=node_line,
                    character=node_column,
                    relative_to=anchor_abs_start,
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

    last_token_pos = Position(line=node_line, character=node_column)

    if len(nodes) <= 1:
        return (
            nodes,
            last_token_pos,
        )

    block = [
        SemanticBlock(
            local_key=local_key,
            index_key=index_key,
            anchor_rel=Range(
                start=_compute_rel_position(
                    line=yaml_node.start_mark.line,
                    character=yaml_node.start_mark.column,
                    relative_to=anchor_abs_start,
                ),
                end=_compute_rel_position(
                    line=yaml_node.end_mark.line,
                    character=yaml_node.end_mark.column,
                    relative_to=anchor_abs_start,
                ),
            ),
            children=nodes,
        )
    ]
    return (block, last_token_pos)


def _extract_value_semantic_info(
    anchor_abs_start: Position,
    last_token_abs_start: Position,
    yaml_node: Node,
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
                anchor_rel=Range(
                    start=_compute_rel_position(
                        line=yaml_node.start_mark.line,
                        character=yaml_node.start_mark.column,
                        relative_to=anchor_abs_start,
                    ),
                    end=_compute_rel_position(
                        line=yaml_node.end_mark.line,
                        character=yaml_node.end_mark.column,
                        relative_to=anchor_abs_start,
                    ),
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


def _compute_rel_position(line: int, character: int, relative_to: Position) -> Position:
    rel_to_line = relative_to.line
    rel_to_offset = relative_to.character

    rel_line = line - rel_to_line
    return Position(
        line=rel_line,
        character=character if rel_line > 0 else (character - rel_to_offset),
    )
