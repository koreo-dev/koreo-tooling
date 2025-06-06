"""Tests for Koreo schema validation"""

import pytest
from lsprotocol import types

from koreo_tooling.error_handling import ValidationError
from koreo_tooling.schema_validation import (
    validate_koreo_yaml,
    validate_koreo_document,
    get_diagnostics_for_file
)


class TestSchemaValidation:
    """Test cases for schema validation functionality"""
    
    def test_valid_value_function(self):
        """Test validation of a valid ValueFunction"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: test-function
spec:
  return:
    result: =inputs.value * 2
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) == 0
    
    def test_missing_required_fields(self):
        """Test validation catches missing required fields"""
        yaml_content = """
kind: ValueFunction
spec:
  return:
    result: =true
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) >= 2  # Missing apiVersion and metadata
        
        # Check that we get errors for missing fields
        error_messages = [e.message for e in errors]
        assert any("apiVersion" in msg for msg in error_messages)
        assert any("metadata" in msg for msg in error_messages)
    
    def test_invalid_api_version(self):
        """Test validation warns on invalid API version"""
        yaml_content = """
apiVersion: wrong.api/v1
kind: ValueFunction
metadata:
  name: test-function
spec:
  return:
    result: =true
"""
        errors = validate_koreo_yaml(yaml_content)
        warnings = [e for e in errors if e.severity == types.DiagnosticSeverity.Warning]
        assert len(warnings) >= 1
        assert any("apiVersion" in w.message for w in warnings)
    
    def test_unknown_kind(self):
        """Test validation catches unknown resource kinds"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: UnknownResource
metadata:
  name: test-resource
spec:
  foo: bar
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) >= 1
        assert any("Unknown resource kind" in e.message for e in errors)
    
    def test_invalid_metadata_name(self):
        """Test validation catches invalid metadata names"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: "test function with spaces"
spec:
  return:
    result: =true
"""
        errors = validate_koreo_yaml(yaml_content)
        warnings = [e for e in errors if e.severity == types.DiagnosticSeverity.Warning]
        assert len(warnings) >= 1
        assert any("metadata.name" in w.message for w in warnings)
    
    def test_yaml_parsing_error(self):
        """Test handling of YAML parsing errors"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
  invalid: yaml indentation
metadata:
  name: test
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) >= 1
        assert any("YAML parsing error" in str(e.message) for e in errors)
    
    def test_workflow_validation(self):
        """Test validation of Workflow resources"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: Workflow
metadata:
  name: test-workflow
spec:
  steps:
    - label: step_one
      ref:
        kind: ValueFunction
        name: some-function
      inputs:
        value: =inputs.data
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) == 0
    
    def test_resource_function_validation(self):
        """Test validation of ResourceFunction resources"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: ResourceFunction
metadata:
  name: test-resource-func
spec:
  apiConfig:
    apiVersion: apps/v1
    kind: Deployment
    name: test-deployment
  resource:
    metadata:
      name: =inputs.name
    spec:
      replicas: =inputs.replicas
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) == 0
    
    def test_function_test_validation(self):
        """Test validation of FunctionTest resources"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: FunctionTest
metadata:
  name: test-function-test
spec:
  functionRef:
    kind: ValueFunction
    name: target-function
  testCases:
    - label: test_case_1
      inputs:
        value: 10
      expectReturn:
        result: 20
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) == 0
    
    def test_multiple_documents(self):
        """Test validation of multiple documents in one file"""
        yaml_content = """
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: func1
spec:
  return:
    result: =true
---
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: func2
spec:
  return:
    result: =false
"""
        errors = validate_koreo_yaml(yaml_content)
        assert len(errors) == 0
    
    def test_validation_error_to_diagnostic(self):
        """Test conversion of ValidationError to LSP Diagnostic"""
        error = ValidationError(
            message="Test error",
            path="spec.field",
            line=5,
            character=10,
            severity=types.DiagnosticSeverity.Error,
            source="koreo-schema"
        )
        
        diagnostic = error.to_diagnostic()
        assert diagnostic.message == "Test error"
        assert diagnostic.severity == types.DiagnosticSeverity.Error
        assert diagnostic.source == "koreo-schema"
        assert diagnostic.range.start.line == 5
        assert diagnostic.range.start.character == 10
    
    def test_get_diagnostics_for_file(self):
        """Test getting LSP diagnostics for a file"""
        yaml_content = """
kind: ValueFunction
"""
        diagnostics = get_diagnostics_for_file(yaml_content)
        assert len(diagnostics) >= 1
        assert all(isinstance(d, types.Diagnostic) for d in diagnostics)