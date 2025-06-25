"""Tests for K8s validation functionality."""

import pytest
from unittest.mock import Mock, patch
from lsprotocol import types

from koreo_tooling.k8s_validation import (
    validate_resource_function,
    validate_spec,
    is_k8s_validation_enabled,
    set_k8s_validation_enabled,
)
from koreo_tooling.error_handling import ValidationError


class TestK8sValidation:
    """Test suite for K8s validation functions."""

    def setup_method(self):
        """Setup for each test method."""
        # Ensure K8s validation is enabled for tests
        set_k8s_validation_enabled(True)

    def test_validate_resource_function_with_invalid_types(self):
        """Test validation detects multiple type errors."""
        spec = {
            "apiConfig": {
                "apiVersion": "aws.konfigurate.realkinetic.com/v1beta1",
                "kind": "AwsEnvironment",
                "name": "=inputs.metadata.name",
                "namespace": "=inputs.namespaceName",
                "plural": "awsenvironments",
            },
            "resource": {
                "spec": {
                    "autoScalingGroup": {
                        "maxReplicas": "invalid_string",  # Should be integer
                        "minReplicas": "another_string",  # Should be integer
                        "targetCapacity": 49,  # Valid integer
                    }
                }
            },
        }

        with patch("koreo_tooling.k8s_validation.get_crd_schema") as mock_get_schema:
            # Mock a schema that requires maxReplicas and minReplicas to be integers
            mock_schema = {
                "properties": {
                    "spec": {
                        "type": "object",
                        "properties": {
                            "autoScalingGroup": {
                                "type": "object",
                                "properties": {
                                    "maxReplicas": {"type": "integer"},
                                    "minReplicas": {"type": "integer"},
                                    "targetCapacity": {"type": "integer"},
                                },
                            }
                        },
                    }
                }
            }
            mock_get_schema.return_value = mock_schema

            errors = validate_resource_function(spec)

            assert len(errors) == 2
            error_messages = [error.message for error in errors]
            assert any("maxReplicas must be integer" in msg for msg in error_messages)
            assert any("minReplicas must be integer" in msg for msg in error_messages)

    def test_validate_resource_function_with_valid_spec(self):
        """Test validation passes with valid specification."""
        spec = {
            "apiConfig": {
                "apiVersion": "aws.konfigurate.realkinetic.com/v1beta1",
                "kind": "AwsEnvironment",
                "plural": "awsenvironments",
            },
            "resource": {
                "spec": {
                    "autoScalingGroup": {
                        "maxReplicas": 10,  # Valid integer
                        "minReplicas": 1,   # Valid integer
                        "targetCapacity": 49,
                    }
                }
            },
        }

        with patch("koreo_tooling.k8s_validation.get_crd_schema") as mock_get_schema:
            mock_schema = {
                "properties": {
                    "spec": {
                        "type": "object",
                        "properties": {
                            "autoScalingGroup": {
                                "type": "object",
                                "properties": {
                                    "maxReplicas": {"type": "integer"},
                                    "minReplicas": {"type": "integer"},
                                    "targetCapacity": {"type": "integer"},
                                },
                            }
                        },
                    }
                }
            }
            mock_get_schema.return_value = mock_schema

            errors = validate_resource_function(spec)
            assert len(errors) == 0

    def test_validate_resource_function_disabled(self):
        """Test validation returns empty when disabled."""
        set_k8s_validation_enabled(False)
        
        spec = {
            "apiConfig": {
                "apiVersion": "aws.konfigurate.realkinetic.com/v1beta1",
                "kind": "AwsEnvironment",
                "plural": "awsenvironments",
            },
            "resource": {
                "spec": {
                    "autoScalingGroup": {
                        "maxReplicas": "invalid_string",
                    }
                }
            },
        }

        errors = validate_resource_function(spec)
        assert len(errors) == 0

    def test_validate_resource_function_missing_plural(self):
        """Test validation requires explicit plural field."""
        spec = {
            "apiConfig": {
                "apiVersion": "nonexistent.example.com/v1",
                "kind": "NonexistentKind",
                # Missing plural field
            },
            "resource": {"spec": {}},
        }

        errors = validate_resource_function(spec)
        assert len(errors) == 1
        assert errors[0].path == "spec.apiConfig"
        assert "Missing required 'plural' field" in errors[0].message

    def test_validate_resource_function_missing_crd(self):
        """Test validation handles missing CRD gracefully when plural is provided."""
        spec = {
            "apiConfig": {
                "apiVersion": "nonexistent.example.com/v1",
                "kind": "NonexistentKind",
                "plural": "nonexistentkinds",
            },
            "resource": {"spec": {}},
        }

        with patch("koreo_tooling.k8s_validation.get_crd_schema") as mock_get_schema:
            mock_get_schema.return_value = None

            errors = validate_resource_function(spec)
            assert len(errors) == 0

    def test_validate_spec_custom_validation_logic(self):
        """Test the custom validation logic that detects multiple errors."""
        spec_data = {
            "autoScalingGroup": {
                "maxReplicas": "string_value",  # Should be integer
                "minReplicas": "another_string",  # Should be integer
                "enabled": "not_boolean",       # Should be boolean
                "targetCapacity": 49,           # Valid integer
            }
        }
        
        schema = {
            "properties": {
                "autoScalingGroup": {
                    "type": "object",
                    "properties": {
                        "maxReplicas": {"type": "integer"},
                        "minReplicas": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                        "targetCapacity": {"type": "integer"},
                    },
                }
            }
        }

        with patch("koreo_tooling.k8s_validation.get_crd_schema") as mock_get_schema:
            mock_get_schema.return_value = schema

            errors = validate_spec(spec_data, "test.example.com/v1", "TestKind", "testkinds")
            
            assert len(errors) >= 2  # Should detect multiple type errors
            error_str = " ".join(errors)
            assert "maxReplicas must be integer" in error_str
            assert "minReplicas must be integer" in error_str

    def test_validation_error_creation(self):
        """Test ValidationError creation and diagnostic conversion."""
        error = ValidationError(
            message="spec.autoScalingGroup.maxReplicas must be integer",
            path="spec.resource",
            line=22,
            character=8,
        )

        diagnostic = error.to_diagnostic()
        
        assert isinstance(diagnostic, types.Diagnostic)
        assert diagnostic.message == "spec.autoScalingGroup.maxReplicas must be integer"
        assert diagnostic.range.start.line == 22
        assert diagnostic.range.start.character == 8
        assert diagnostic.severity == types.DiagnosticSeverity.Error
        assert diagnostic.source == "koreo"

    def test_k8s_validation_enable_disable(self):
        """Test enabling and disabling K8s validation."""
        # Test enabling
        set_k8s_validation_enabled(True)
        assert is_k8s_validation_enabled() is True

        # Test disabling
        set_k8s_validation_enabled(False)
        assert is_k8s_validation_enabled() is False

    def test_cel_expression_handling(self):
        """Test validation handles CEL expressions correctly."""
        spec = {
            "apiConfig": {
                "apiVersion": "aws.konfigurate.realkinetic.com/v1beta1",
                "kind": "AwsEnvironment",
                "plural": "awsenvironments",
            },
            "resource": {
                "spec": {
                    "name": "=inputs.metadata.name",  # CEL expression
                    "autoScalingGroup": {
                        "maxReplicas": "invalid_string",  # Should still be caught
                    }
                }
            },
        }

        with patch("koreo_tooling.k8s_validation.get_crd_schema") as mock_get_schema:
            mock_schema = {
                "properties": {
                    "spec": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "autoScalingGroup": {
                                "type": "object",
                                "properties": {
                                    "maxReplicas": {"type": "integer"},
                                },
                            }
                        },
                    }
                }
            }
            mock_get_schema.return_value = mock_schema

            errors = validate_resource_function(spec)
            
            # Should detect the type error but not complain about CEL expression
            assert len(errors) >= 1
            error_messages = [error.message for error in errors]
            assert any("maxReplicas must be integer" in msg for msg in error_messages)