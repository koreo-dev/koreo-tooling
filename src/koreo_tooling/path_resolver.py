"""Simple path resolution using existing indexing infrastructure"""

import logging
from typing import Any

from lsprotocol import types

from .indexing.semantics import (
    SemanticAnchor,
    generate_local_range_index,
    generate_key_range_index,
    compute_abs_range
)

logger = logging.getLogger("koreo.tooling.path_resolver")


class SemanticPathResolver:
    """Resolve YAML paths using semantic indexing instead of manual line searching"""
    
    def __init__(self, semantic_anchor: SemanticAnchor):
        self.anchor = semantic_anchor
        self.local_index = dict(generate_local_range_index(semantic_anchor, semantic_anchor))
        self.key_index = dict(generate_key_range_index(semantic_anchor, semantic_anchor))
    
    def get_position_for_path(self, path: str) -> types.Position | None:
        """Get position for a path using semantic indexing"""
        # Try direct lookup in local index first
        if path in self.local_index:
            range_info = self.local_index[path]
            return range_info.start
        
        # Try key index
        if path in self.key_index:
            range_info = self.key_index[path]
            return range_info.start
        
        # Try variations of the path
        variations = self._generate_path_variations(path)
        for variant in variations:
            if variant in self.local_index:
                range_info = self.local_index[variant]
                return range_info.start
            if variant in self.key_index:
                range_info = self.key_index[variant]
                return range_info.start
        
        logger.debug(f"No position found for path: {path}")
        return None
    
    def get_range_for_path(self, path: str) -> types.Range | None:
        """Get range for a path using semantic indexing"""
        # Try direct lookup in local index first
        if path in self.local_index:
            return self.local_index[path]
        
        # Try key index
        if path in self.key_index:
            return self.key_index[path]
        
        # Try variations
        variations = self._generate_path_variations(path)
        for variant in variations:
            if variant in self.local_index:
                return self.local_index[variant]
            if variant in self.key_index:
                return self.key_index[variant]
        
        return None
    
    def _generate_path_variations(self, path: str) -> list[str]:
        """Generate common variations of a path for lookup"""
        variations = []
        
        # Handle array access patterns
        if '[' in path and ']' in path:
            # Convert spec.testCases[0].currentResource to alternatives
            parts = path.split('.')
            for i, part in enumerate(parts):
                if '[' in part:
                    # Try without the array index
                    base_part = part.split('[')[0]
                    alt_parts = parts[:i] + [base_part] + parts[i+1:]
                    variations.append('.'.join(alt_parts))
        
        # Add common prefixes/suffixes
        if not path.startswith('spec.') and '.' in path:
            variations.append(f"spec.{path}")
        
        if path.endswith('_key'):
            variations.append(path[:-4])  # Remove _key suffix
        else:
            variations.append(f"{path}_key")  # Add _key suffix
        
        return variations
    
    def list_available_paths(self) -> dict[str, types.Range]:
        """List all available paths for debugging"""
        all_paths = {}
        all_paths.update(self.local_index)
        all_paths.update(self.key_index)
        return all_paths


def resolve_path_position(semantic_anchor: SemanticAnchor, path: str) -> types.Position | None:
    """Convenience function to resolve a path position using semantic indexing"""
    resolver = SemanticPathResolver(semantic_anchor)
    return resolver.get_position_for_path(path)


def resolve_path_range(semantic_anchor: SemanticAnchor, path: str) -> types.Range | None:
    """Convenience function to resolve a path range using semantic indexing"""
    resolver = SemanticPathResolver(semantic_anchor)
    return resolver.get_range_for_path(path)