"""Shared YAML processing utilities with position tracking"""

import logging
from collections.abc import Generator

import yaml
from lsprotocol import types

logger = logging.getLogger("koreo.tooling.yaml_utils")


class YamlPositionTracker:
    """Tracks line and column positions for YAML paths during parsing"""
    
    def __init__(self, yaml_content: str):
        self.yaml_content = yaml_content
        self.lines = yaml_content.split('\n')
        self.path_to_position = {}
        self._parse_with_positions()
    
    def _parse_with_positions(self):
        """Parse YAML and build path to line number mapping"""
        try:
            loader = yaml.SafeLoader(self.yaml_content)
            node = loader.get_single_node()
            if node:
                self._traverse_node(node, [])
        except yaml.YAMLError:
            pass
    
    def _traverse_node(self, node, path):
        """Recursively traverse YAML nodes and record positions"""
        if hasattr(node, 'start_mark'):
            path_str = '.'.join(path) if path else 'root'
            self.path_to_position[path_str] = {
                'line': node.start_mark.line,
                'column': node.start_mark.column,
                'end_line': node.end_mark.line if hasattr(node, 'end_mark') else None,
                'end_column': node.end_mark.column if hasattr(node, 'end_mark') else None
            }
        
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    key = key_node.value
                    new_path = path + [key]
                    
                    # Record key position
                    key_path_str = '.'.join(new_path)
                    self.path_to_position[key_path_str + '_key'] = {
                        'line': key_node.start_mark.line,
                        'column': key_node.start_mark.column
                    }
                    
                    # Traverse value
                    self._traverse_node(value_node, new_path)
        
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                new_path = path + [f'[{i}]']
                self._traverse_node(item, new_path)
    
    def get_position(self, path: str) -> dict | None:
        """Get line/column for a given path"""
        # Try exact match first
        if path in self.path_to_position:
            return self.path_to_position[path]
        
        # Try to find parent path for missing field errors
        parts = path.split('.')
        while parts:
            parent_path = '.'.join(parts)
            if parent_path in self.path_to_position:
                return self.path_to_position[parent_path]
            parts.pop()
        
        return None


class YamlProcessor:
    """Centralized YAML processing with error handling and position tracking"""
    
    @staticmethod
    def safe_load_all(yaml_content: str) -> tuple[list[dict], list[yaml.YAMLError]]:
        """Load all YAML documents with error collection"""
        documents = []
        errors = []
        
        try:
            docs = list(yaml.safe_load_all(yaml_content))
            documents = [doc for doc in docs if doc is not None]
        except yaml.YAMLError as e:
            errors.append(e)
        
        return documents, errors
    
    @staticmethod
    def safe_load_all_with_positions(yaml_content: str) -> Generator[tuple[dict, YamlPositionTracker]]:
        """Load YAML documents with position tracking"""
        try:
            # Split multi-document YAML by document separators
            doc_parts = yaml_content.split('\n---\n')
            
            for doc_content in doc_parts:
                if doc_content.strip():
                    try:
                        doc = yaml.safe_load(doc_content)
                        if doc:
                            tracker = YamlPositionTracker(doc_content)
                            yield doc, tracker
                    except yaml.YAMLError:
                        continue
        except Exception:
            # Fallback to simple loading
            docs, _ = YamlProcessor.safe_load_all(yaml_content)
            for doc in docs:
                tracker = YamlPositionTracker(yaml_content)
                yield doc, tracker
    
    @staticmethod
    def get_yaml_parse_error_position(error: yaml.YAMLError) -> types.Position | None:
        """Extract position from YAML parsing error"""
        if hasattr(error, 'problem_mark') and error.problem_mark:
            return types.Position(
                line=error.problem_mark.line,
                character=error.problem_mark.column
            )
        return None
    
    @staticmethod
    def find_line_for_path(yaml_lines: list[str], path: str) -> int | None:
        """Simple line search for specific paths (fallback method)"""
        if path == "spec.resource":
            # Look for the resource: section and then the spec: line under it
            resource_line = None
            spec_line = None
            
            for i, line in enumerate(yaml_lines):
                # Find "resource:" line (with proper indentation)
                if 'resource:' in line:
                    resource_line = i
                # Find "spec:" line after resource line
                elif resource_line is not None and 'spec:' in line and i > resource_line:
                    spec_line = i
                    break
            
            return spec_line
        
        return None