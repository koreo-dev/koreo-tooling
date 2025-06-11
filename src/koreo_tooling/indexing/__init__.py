from __future__ import annotations

import hashlib
import io

from ruamel.yaml.composer import Composer
from ruamel.yaml.constructor import RoundTripConstructor
from ruamel.yaml.nodes import Node
from ruamel.yaml.parser import RoundTripParser
from ruamel.yaml.reader import Reader
from ruamel.yaml.resolver import VersionedResolver
from ruamel.yaml.scanner import RoundTripScanner

from .extractor import extract_semantic_structure_info
from .koreo_semantics import ALL, SEMANTIC_TYPE_STRUCTURE
from .semantics import (
    Position,
    SemanticAnchor,
    SemanticStructure,
    TokenModifiers,
    TokenTypes,
    compute_abs_range,
)

STRUCTURE_KEY = "..structure.."

__all__ = [
    "IndexingLoader",
    "IndexingConstructor",
    "STRUCTURE_KEY",
    "SemanticAnchor",
    "TokenModifiers",
    "TokenTypes",
    "compute_abs_range",
]


class IndexingConstructor(RoundTripConstructor):
    def __init__(self, doc, preserve_quotes=True, loader=None):
        super().__init__(preserve_quotes=preserve_quotes, loader=loader)
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
            doc_semantics = SEMANTIC_TYPE_STRUCTURE.get(
                ALL, SemanticStructure()
            )

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


class IndexingLoader:
    """Custom YAML loader preserving node info and semantic structure."""

    def __init__(self, stream, doc):
        self.stream = stream
        self.doc = doc
        # Set default YAML attributes
        self.processing_version = (1, 2)
        self.allow_duplicate_keys = False
        self.preserve_quotes = True
        self.width = 4096
        self.comment_handling = None
        self.yaml_version = None
        self._setup_components()

    def check_data(self):
        """Check if more data is available in the stream."""
        return self.composer.check_node()

    def get_data(self):
        """Get the next constructed document."""
        if self.composer.check_node():
            # Get the node
            node = self.composer.get_node()
            if node is not None:
                # Construct document using our custom constructor
                return self.constructor.construct_document(node)
        return None

    def dispose(self):
        """Clean up the loader."""
        try:
            self.reader.reset_reader()
        except Exception:
            pass

    def _setup_components(self):
        """Set up the internal components."""
        if isinstance(self.stream, str):
            stream = io.StringIO(self.stream)
        else:
            stream = self.stream

        # Create reader first
        self.reader = Reader(stream)
        self._reader = self.reader

        # Create other components
        self.scanner = RoundTripScanner(loader=self)
        self._scanner = self.scanner

        self.parser = RoundTripParser(loader=self)
        self._parser = self.parser

        self.composer = Composer(loader=self)
        self._composer = self.composer

        self.constructor = IndexingConstructor(
            doc=self.doc, preserve_quotes=True, loader=self
        )
        self._constructor = self.constructor

        self.resolver = VersionedResolver(loader=self)
        self._resolver = self.resolver
