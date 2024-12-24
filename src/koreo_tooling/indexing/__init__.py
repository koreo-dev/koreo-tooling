from __future__ import annotations
import hashlib

from yaml.loader import SafeLoader
from yaml.nodes import Node


from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE
from .semantics import (
    Position,
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    SemanticStructure,
    TokenModifiers,
    TokenTypes,
    compute_abs_position,
    compute_abs_range,
)

from .extractor import extract_semantic_structure_info

STRUCTURE_KEY = "..structure.."


class IndexingLoader(SafeLoader):
    def __init__(self, *args, doc, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_node_abs_start = Position(line=0, character=0)
        self.last_node_abs_end = Position(line=0, character=0)
        self.doc = doc
        self.doc_count = 0

    def construct_document(self, node: Node):
        yaml_doc = super().construct_document(node)
        if not yaml_doc:
            self.doc_count = self.doc_count + 1
            return

        start_line = node.start_mark.line
        end_line = node.end_mark.line
        block_value = ("\n".join(self.doc.lines[start_line:end_line])).encode()
        block_hash = hashlib.md5(block_value, usedforsecurity=False).hexdigest()

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
            character=node.start_mark.column,
        )

        anchor_rel_start = Position(
            line=node.start_mark.line - self.last_node_abs_start.line,
            character=node.start_mark.column,
        )

        structure, last_abs_start = extract_semantic_structure_info(
            anchor_abs_start=anchor_abs_start,
            last_token_abs_start=self.last_node_abs_start,
            yaml_node=node,
            doc=self.doc,
            semantic_type=doc_semantics,
        )
        yaml_doc[STRUCTURE_KEY] = SemanticAnchor(
            key=anchor_key,
            abs_position=anchor_abs_start,
            rel_position=anchor_rel_start,
            children=structure,
        )

        self.last_node_abs_start = last_abs_start

        self.doc_count = self.doc_count + 1

        return block_hash, yaml_doc
