"""Shared YAML processing utilities with position tracking"""

import logging
import re
from collections.abc import Generator

import yaml
from lsprotocol import types

logger = logging.getLogger("koreo.tooling.yaml_utils")

# Compiled regex patterns for performance
_FUNCTION_TEST_PATH_PATTERN = re.compile(r'spec\.testCases\[(\d+)\]\.(\w+)\.spec\.(\w+)')
_SIMPLE_FUNCTION_TEST_PATTERN = re.compile(r'spec\.testCases\[(\d+)\]\.(\w+)')


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