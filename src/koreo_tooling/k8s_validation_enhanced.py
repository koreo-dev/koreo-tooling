"""Enhanced K8s validation with line number mapping for better diagnostics"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import yaml
from lsprotocol import types

try:
    from .k8s_validation import validate_resource_function
except ImportError:
    from koreo_tooling.k8s_validation import validate_resource_function

logger = logging.getLogger("koreo.tooling.k8s_validation_enhanced")


@dataclass
class PositionedError:
    """Error with position information for VS Code diagnostics"""
    message: str
    path: str
    line: int
    column: int
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error


class YamlPositionTracker:
    """Tracks line numbers for YAML paths during parsing"""
    
    def __init__(self, yaml_content: str):
        self.yaml_content = yaml_content
        self.path_to_line = {}
        self._parse_with_positions()
    
    def _parse_with_positions(self):
        """Parse YAML and build path to line number mapping"""
        try:
            # Use yaml.compose to get node position information
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
            self.path_to_line[path_str] = {
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
                    self.path_to_line[key_path_str + '_key'] = {
                        'line': key_node.start_mark.line,
                        'column': key_node.start_mark.column
                    }
                    
                    # Traverse value
                    self._traverse_node(value_node, new_path)
        
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                new_path = path + [f'[{i}]']
                self._traverse_node(item, new_path)
    
    def get_position(self, path: str) -> Optional[dict]:
        """Get line/column for a given path"""
        # Try exact match first
        if path in self.path_to_line:
            return self.path_to_line[path]
        
        # Try to find parent path for missing field errors
        parts = path.split('.')
        while parts:
            parent_path = '.'.join(parts)
            if parent_path in self.path_to_line:
                return self.path_to_line[parent_path]
            parts.pop()
        
        return None


def map_error_to_position(error: dict, position_tracker: YamlPositionTracker, 
                         yaml_lines: list[str]) -> PositionedError:
    """Map validation error to specific line position"""
    path = error.get('path', '')
    message = error.get('message', '')
    
    # Simple approach: find the spec line under resource section
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
        
        if spec_line is not None:
            # Find the column position of "spec"
            spec_match = re.search(r'(\s*)spec:', yaml_lines[spec_line])
            column = len(spec_match.group(1)) if spec_match else 0
            
            return PositionedError(
                message=message,
                path=path,
                line=spec_line,
                column=column,
                end_line=spec_line,
                end_column=column + 4,  # Length of "spec"
                severity=types.DiagnosticSeverity.Error
            )
    
    # For other errors or fallback, just use line 0
    return PositionedError(
        message=message,
        path=path,
        line=0,
        column=0,
        severity=types.DiagnosticSeverity.Error
    )


def _extract_field_from_message(message: str) -> Optional[str]:
    """Extract field name from error message"""
    import re
    
    # Pattern for "Unknown field 'fieldname'"
    match = re.search(r"Unknown field '([^']+)'", message)
    if match:
        return match.group(1)
    
    # Pattern for "additional property 'fieldname'"
    match = re.search(r"additional property '([^']+)'", message)
    if match:
        return match.group(1)
    
    # Pattern for field names in square brackets
    match = re.search(r"\['([^']+)'\]", message)
    if match:
        return match.group(1)
    
    return None


def validate_resource_function_with_positions(yaml_content: str) -> list[PositionedError]:
    """Validate ResourceFunction and return errors with line positions"""
    errors = []
    
    try:
        # Parse YAML documents
        docs = list(yaml.safe_load_all(yaml_content))
        yaml_lines = yaml_content.split('\n')
        
        # Create position tracker
        tracker = YamlPositionTracker(yaml_content)
        
        
        # Find ResourceFunction documents
        for doc in docs:
            if doc and doc.get('kind') == 'ResourceFunction':
                spec = doc.get('spec', {})
                
                # Run validation
                validation_errors = validate_resource_function(spec)
                
                # Map errors to positions
                for error in validation_errors:
                    error_dict = {
                        'path': error.path,
                        'message': error.message,
                        'severity': error.severity
                    }
                    positioned_error = map_error_to_position(error_dict, tracker, yaml_lines)
                    errors.append(positioned_error)
    
    except yaml.YAMLError as e:
        # YAML parsing error
        if hasattr(e, 'problem_mark'):
            errors.append(PositionedError(
                message=f"YAML parsing error: {e}",
                path='',
                line=e.problem_mark.line,
                column=e.problem_mark.column,
                severity=types.DiagnosticSeverity.Error
            ))
    
    return errors


def get_enhanced_diagnostics(yaml_content: str) -> list[types.Diagnostic]:
    """Get VS Code diagnostics with proper line positions"""
    errors = validate_resource_function_with_positions(yaml_content)
    diagnostics = []
    
    for error in errors:
        # Create range for the error
        start = types.Position(line=error.line, character=error.column)
        
        # For end position, use provided end or estimate based on error type
        if error.end_line is not None and error.end_column is not None:
            end = types.Position(line=error.end_line, character=error.end_column)
        else:
            # Use the end position from the error
            end = types.Position(line=error.end_line or error.line, 
                               character=error.end_column or (error.column + 20))
        
        diagnostics.append(types.Diagnostic(
            range=types.Range(start=start, end=end),
            message=error.message,
            severity=error.severity,
            source="koreo-k8s"
        ))
    
    return diagnostics