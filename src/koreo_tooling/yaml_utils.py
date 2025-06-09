"""Enhanced YAML processing utilities using ruamel.yaml for better position tracking"""

import logging
import re
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

logger = logging.getLogger("koreo.tooling.yaml_utils")

# Compiled regex patterns for performance
_FUNCTION_TEST_PATH_PATTERN = re.compile(r'spec\.testCases\[(\d+)\]\.(\w+)\.spec\.(\w+)')
_SIMPLE_FUNCTION_TEST_PATTERN = re.compile(r'spec\.testCases\[(\d+)\]\.(\w+)')


class YamlPositionTracker:
    """Enhanced position tracker using ruamel.yaml's native capabilities"""
    
    def __init__(self, yaml_content: str, document: Any = None):
        self.yaml_content = yaml_content
        self.lines = yaml_content.split('\n')
        self.document = document
        self.processor = EnhancedYamlProcessor()
    
    def get_position(self, path: str) -> dict | None:
        """Get line/column for a given path using ruamel.yaml's position data"""
        if not self.document:
            return None
        
        # Navigate to the object at the given path
        obj = self._navigate_to_path(self.document, path)
        if obj is None:
            return self._fallback_position_search(path)
        
        # Get position info from ruamel.yaml metadata
        pos_info = get_yaml_position(obj)
        if pos_info:
            return {
                'line': pos_info.line,
                'column': pos_info.column,
                'end_line': pos_info.end_line,
                'end_column': pos_info.end_column
            }
        
        # Fallback to line search
        return self._fallback_position_search(path)
    
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
    
    def _fallback_position_search(self, path: str) -> dict | None:
        """Fallback to line search when ruamel.yaml position data is unavailable"""
        line_num = YamlProcessor.find_line_for_path(self.lines, path)
        if line_num is not None:
            return {
                'line': line_num,
                'column': 0,
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
        
        # Handle FunctionTest paths like spec.testCases[0].currentResource or spec.testCases[0].expectResource.spec.cidrBlock
        if "testCases[" in path:
            # Handle deeper paths like spec.testCases[0].expectResource.spec.cidrBlock
            deep_match = _FUNCTION_TEST_PATH_PATTERN.match(path)
            if deep_match:
                test_index = int(deep_match.group(1))
                resource_type = deep_match.group(2)  # currentResource or expectResource
                field_name = deep_match.group(3)     # cidrBlock, etc.
                
                # Find testCases array and the specific resource, then the field
                in_test_cases = False
                test_case_count = -1
                
                # Optimize: limit search range for large files
                max_search_lines = min(len(yaml_lines), 500)  # Don't search beyond 500 lines
                
                for i, line in enumerate(yaml_lines[:max_search_lines]):
                    if 'testCases:' in line:
                        in_test_cases = True
                        continue
                    
                    if in_test_cases:
                        # Look for test case entries
                        if line.strip().startswith('- ') and ('label:' in line or 'expectResource:' in line):
                            test_case_count += 1
                            if test_case_count == test_index:
                                # Now look for the specific resource type (limited range)
                                search_end = min(i + 80, len(yaml_lines))
                                for j in range(i, search_end):
                                    if f'{resource_type}:' in yaml_lines[j]:
                                        # Found the resource, now look for spec: and then the field
                                        spec_search_end = min(j + 40, len(yaml_lines))
                                        for k in range(j, spec_search_end):
                                            if 'spec:' in yaml_lines[k]:
                                                # Found spec, now look for the specific field
                                                field_search_end = min(k + 25, len(yaml_lines))
                                                for l in range(k, field_search_end):
                                                    if f'{field_name}:' in yaml_lines[l]:
                                                        return l
                                                break
                                        break
                                break
                        # Early exit if we've found too many test cases
                        elif test_case_count > test_index + 5:
                            break
            
            # Handle simpler paths like spec.testCases[0].currentResource
            match = _SIMPLE_FUNCTION_TEST_PATTERN.match(path)
            if match:
                test_index = int(match.group(1))
                field_name = match.group(2)
                
                # Find testCases array
                in_test_cases = False
                test_case_count = -1
                
                for i, line in enumerate(yaml_lines):
                    if 'testCases:' in line:
                        in_test_cases = True
                        continue
                    
                    if in_test_cases:
                        # Look for test case entries (starts with - label:)
                        if line.strip().startswith('- ') and ('label:' in line or 'expectResource:' in line):
                            test_case_count += 1
                            if test_case_count == test_index:
                                # Now look for the specific field
                                for j in range(i, min(i + 50, len(yaml_lines))):
                                    if f'{field_name}:' in yaml_lines[j]:
                                        return j
                                break
        
        # Handle simple paths like spec.currentResource
        path_parts = path.split('.')
        if len(path_parts) >= 2:
            field_name = path_parts[-1]
            parent_path = '.'.join(path_parts[:-1])
            
            # Look for the field name in the YAML
            for i, line in enumerate(yaml_lines):
                if f'{field_name}:' in line:
                    # Check if we're in the right context (e.g., under spec)
                    if parent_path == 'spec':
                        # Make sure we're after a spec: line
                        for j in range(max(0, i - 20), i):
                            if 'spec:' in yaml_lines[j]:
                                return i
                    else:
                        return i
        
        return None