"""Enhanced YAML processing utilities using ruamel.yaml for better position tracking"""

import logging
from collections.abc import Generator
from typing import Any

from lsprotocol import types

from .yaml_processor import (
    EnhancedYamlProcessor, 
    YamlPositionInfo, 
    YamlProcessingError,
    load_yaml_with_positions,
    get_yaml_position,
    validate_yaml
)
from .path_resolver import SemanticPathResolver

logger = logging.getLogger("koreo.tooling.yaml_utils")



class YamlPositionTracker:
    """Enhanced position tracker using semantic indexing and ruamel.yaml"""
    
    def __init__(self, yaml_content: str, document: Any = None, semantic_anchor=None):
        self.yaml_content = yaml_content
        self.lines = yaml_content.split('\n')
        self.document = document
        self.semantic_anchor = semantic_anchor
        self.processor = EnhancedYamlProcessor()
        
        # Create path resolver if we have semantic data
        self.path_resolver = None
        if semantic_anchor:
            self.path_resolver = SemanticPathResolver(semantic_anchor)
    
    def get_position(self, path: str) -> dict | None:
        """Get line/column for a given path using semantic indexing first"""
        
        # Try semantic indexing first (much simpler and more reliable)
        if self.path_resolver:
            position = self.path_resolver.get_position_for_path(path)
            if position:
                return {
                    'line': position.line,
                    'column': position.character,
                    'end_line': None,
                    'end_column': None
                }
        
        # Try ruamel.yaml's position data
        if self.document:
            obj = self._navigate_to_path(self.document, path)
            if obj is not None:
                pos_info = get_yaml_position(obj)
                if pos_info:
                    return {
                        'line': pos_info.line,
                        'column': pos_info.column,
                        'end_line': pos_info.end_line,
                        'end_column': pos_info.end_column
                    }
        
        # Last resort: simple fallback
        return self._simple_fallback_search(path)
    
    def _navigate_to_path(self, obj: Any, path: str) -> Any:
        """Navigate to an object using a dot-separated path"""
        if not path or path == 'root':
            return obj
        
        current = obj
        parts = path.split('.')
        
        for part in parts:
            if part.endswith('_key'):
                # This is asking for key position, return the container
                return current
            
            # Handle array indices like [0]
            if '[' in part and ']' in part:
                key = part.split('[')[0]
                index_str = part.split('[')[1].split(']')[0]
                try:
                    index = int(index_str)
                    current = current.get(key, [])[index] if hasattr(current, 'get') else None
                except (ValueError, IndexError, TypeError):
                    return None
            else:
                # Regular key access
                if hasattr(current, 'get'):
                    current = current.get(part)
                else:
                    return None
            
            if current is None:
                break
        
        return current
    
    def _simple_fallback_search(self, path: str) -> dict | None:
        """Simple fallback for basic field lookups"""
        # Just look for the last component of the path
        if '.' in path:
            field_name = path.split('.')[-1]
        else:
            field_name = path
        
        # Remove array indices and key suffixes
        if '[' in field_name:
            field_name = field_name.split('[')[0]
        if field_name.endswith('_key'):
            field_name = field_name[:-4]
        
        # Simple line search for the field
        for i, line in enumerate(self.lines):
            if f'{field_name}:' in line:
                return {
                    'line': i,
                    'column': line.find(f'{field_name}:'),
                    'end_line': None,
                    'end_column': None
                }
        
        return None


class YamlProcessor:
    """Enhanced YAML processor using ruamel.yaml with better error handling"""
    
    @staticmethod
    def safe_load_all(yaml_content: str) -> tuple[list[dict], list[YamlProcessingError]]:
        """Load all YAML documents with error collection"""
        documents = []
        errors = []
        
        for doc, doc_errors in load_yaml_with_positions(yaml_content):
            if doc is not None:
                documents.append(doc)
            errors.extend(doc_errors)
        
        return documents, errors
    
    @staticmethod
    def safe_load_all_with_positions(yaml_content: str) -> Generator[tuple[dict, YamlPositionTracker]]:
        """Load YAML documents with enhanced position tracking"""
        for doc, doc_errors in load_yaml_with_positions(yaml_content):
            if doc is not None:
                tracker = YamlPositionTracker(yaml_content, doc)
                yield doc, tracker
    
    @staticmethod
    def get_yaml_parse_error_position(error: YamlProcessingError) -> types.Position | None:
        """Extract position from YAML processing error"""
        if error.position:
            return types.Position(
                line=error.position.line,
                character=error.position.column
            )
        return None
    
