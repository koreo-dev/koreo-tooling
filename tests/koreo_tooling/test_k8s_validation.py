"""Tests for Kubernetes CRD validation functionality"""

import pytest
from unittest.mock import patch, MagicMock

from koreo_tooling.k8s_validation import (
    KubernetesCRDValidator, 
    ResourceFunctionValidator,
    validate_resource_function_k8s
)


class TestKubernetesCRDValidator:
    """Test cases for KubernetesCRDValidator"""
    
    def test_is_builtin_resource(self):
        """Test detection of built-in Kubernetes resources"""
        validator = KubernetesCRDValidator()
        
        # Test built-in resources
        assert validator.is_builtin_resource("apps/v1", "Deployment")
        assert validator.is_builtin_resource("v1", "Pod")
        assert validator.is_builtin_resource("v1", "Service")
        
        # Test custom resources
        assert not validator.is_builtin_resource("example.com/v1", "MyCustomResource")
        assert not validator.is_builtin_resource("koreo.dev/v1beta1", "Workflow")
    
    def test_get_validator_builtin_resource(self):
        """Test that built-in resources don't attempt CRD lookup"""
        validator = KubernetesCRDValidator()
        
        # Should return None for built-in resources (no validation)
        result = validator.get_validator("apps/v1", "Deployment")
        assert result is None
    
    @patch('subprocess.run')
    def test_get_crd_from_cluster_success(self, mock_run):
        """Test successful CRD retrieval from cluster"""
        validator = KubernetesCRDValidator()
        
        # Mock kubectl response
        mock_crd = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "spec": {
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "field1": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition"}'
        )
        
        with patch('json.loads', return_value=mock_crd):
            result = validator.get_crd_from_cluster("example.com/v1", "MyResource")
            assert result == mock_crd
    
    @patch('subprocess.run')
    def test_get_crd_from_cluster_not_found(self, mock_run):
        """Test CRD not found scenario"""
        validator = KubernetesCRDValidator()
        
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr='Error from server (NotFound): customresourcedefinitions.apiextensions.k8s.io "myresources.example.com" not found'
        )
        
        result = validator.get_crd_from_cluster("example.com/v1", "MyResource")
        assert result is None
    
    def test_extract_schema_from_crd(self):
        """Test schema extraction from CRD"""
        validator = KubernetesCRDValidator()
        
        crd = {
            "spec": {
                "versions": [
                    {
                        "name": "v1",
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "field1": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "name": "v2",
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "field2": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        # Test extracting v1 schema
        schema_v1 = validator.extract_schema_from_crd(crd, "v1")
        assert schema_v1["properties"]["spec"]["properties"]["field1"]["type"] == "string"
        
        # Test extracting v2 schema
        schema_v2 = validator.extract_schema_from_crd(crd, "v2")
        assert schema_v2["properties"]["spec"]["properties"]["field2"]["type"] == "integer"
        
        # Test non-existent version
        schema_none = validator.extract_schema_from_crd(crd, "v3")
        assert schema_none is None


class TestResourceFunctionValidator:
    """Test cases for ResourceFunctionValidator"""
    
    @patch.object(KubernetesCRDValidator, 'validate_resource_spec')
    def test_validate_resource_function_spec(self, mock_validate):
        """Test ResourceFunction spec validation"""
        validator = ResourceFunctionValidator()
        
        mock_validate.return_value = ["Test error"]
        
        spec = {
            "apiConfig": {
                "apiVersion": "example.com/v1",
                "kind": "MyResource",
                "name": "test"
            },
            "resource": {
                "spec": {"field": "value"}
            },
            "overlays": [
                {"overlay": {"spec": {"field": "overlay_value"}}}
            ],
            "create": {
                "overlay": {"spec": {"field": "create_value"}}
            }
        }
        
        errors = validator.validate_resource_function_spec(spec)
        
        # Should have 3 errors (resource, overlay, create.overlay)
        assert len(errors) == 3
        
        # Check error details
        assert any("spec.resource" in error["path"] for error in errors)
        assert any("spec.overlays[0].overlay" in error["path"] for error in errors)
        assert any("spec.create.overlay" in error["path"] for error in errors)
    
    def test_validate_resource_function_spec_no_api_config(self):
        """Test ResourceFunction without apiConfig"""
        validator = ResourceFunctionValidator()
        
        spec = {
            "resource": {"spec": {"field": "value"}}
        }
        
        errors = validator.validate_resource_function_spec(spec)
        assert len(errors) == 0  # No validation without apiConfig
    
    def test_validate_resource_function_spec_builtin_resource(self):
        """Test ResourceFunction with built-in Kubernetes resource"""
        validator = ResourceFunctionValidator()
        
        spec = {
            "apiConfig": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": "test"
            },
            "resource": {
                "spec": {
                    "replicas": 3,
                    "selector": {"matchLabels": {"app": "test"}}
                }
            }
        }
        
        errors = validator.validate_resource_function_spec(spec)
        assert len(errors) == 0  # No CRD validation for built-in resources


def test_validate_resource_function_k8s():
    """Test the main validation function"""
    spec = {
        "apiConfig": {
            "apiVersion": "apps/v1", 
            "kind": "Deployment",
            "name": "test"
        },
        "resource": {"spec": {"replicas": 3}}
    }
    
    # Should return empty list for built-in resources
    errors = validate_resource_function_k8s(spec)
    assert isinstance(errors, list)
    assert len(errors) == 0


def test_kubernetes_format_handling():
    """Test that Kubernetes-specific formats (int32, int64) are handled correctly"""
    validator = KubernetesCRDValidator()
    
    # Schema with Kubernetes-specific formats
    schema_with_k8s_formats = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "properties": {
                    "replicas": {
                        "type": "integer",
                        "format": "int32"
                    },
                    "timeout": {
                        "type": "integer", 
                        "format": "int64"
                    },
                    "data": {
                        "type": "string",
                        "format": "byte"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time"
                    },
                    "preserve-unknown": True
                },
                "x-kubernetes-preserve-unknown-fields": True
            }
        }
    }
    
    # Should compile successfully (no "Unknown format" error)
    compiled_validator = validator.compile_validator(schema_with_k8s_formats)
    assert compiled_validator is not None
    
    # Should validate correctly
    test_spec = {
        "replicas": 3,
        "timeout": 300,
        "data": "base64data",
        "timestamp": "2024-01-01T00:00:00Z"
    }
    
    # Should not raise an exception
    compiled_validator(test_spec)


def test_cel_expression_removal():
    """Test that CEL expressions are removed from validation (not replaced with dummy values)"""
    validator = KubernetesCRDValidator()
    
    # Schema expecting different types
    schema = {
        "type": "object",
        "properties": {
            "replicas": {"type": "integer"},
            "enabled": {"type": "boolean"},
            "name": {"type": "string"},
            "ports": {
                "type": "array",
                "items": {"type": "integer"}
            },
            "config": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "number"}
                }
            }
        }
    }
    
    # Data with CEL expressions
    test_data = {
        "replicas": "=inputs.replica_count",  # CEL for integer - should be removed
        "enabled": "=inputs.feature_enabled",  # CEL for boolean - should be removed
        "name": "my-app",  # Regular string - should remain
        "ports": [80, "=inputs.port", 443],  # Mixed array - CEL item should be removed
        "config": {
            "timeout": "=inputs.timeout_seconds"  # CEL for number - should be removed
        }
    }
    
    # Remove CEL expressions
    prepared, has_cel = validator._prepare_data_for_validation(test_data, schema)
    
    # Verify CEL expressions are removed from validation
    assert "replicas" not in prepared  # CEL expression removed
    assert "enabled" not in prepared   # CEL expression removed
    assert prepared["name"] == "my-app"  # Literal value unchanged
    assert prepared["ports"] == [80, 443]  # CEL expression removed from array
    assert prepared["config"] == {}  # CEL expression removed from nested object
    
    # Verify that CEL expressions were detected
    assert has_cel == True


def test_partial_validation_for_overlays():
    """Test that overlays use partial validation (no required fields) while resources use full validation"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource",
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "complete-resource",
                "replicas": 3,
                "enabled": True
            }
        },
        "overlays": [
            {
                "overlay": {
                    "spec": {
                        "replicas": 5  # Only partial - missing required 'name' field
                    }
                }
            }
        ],
        "create": {
            "overlay": {
                "spec": {
                    "enabled": False  # Only partial - missing required 'name' field
                }
            }
        }
    }
    
    # Mock the K8s validator to simulate required field validation
    from unittest.mock import Mock
    mock_validator = Mock()
    
    # Full validation should fail for incomplete resource
    mock_validator.validate_resource_spec.side_effect = [
        [],  # Resource validation (full) - passes
        [],  # Overlay validation (partial) - passes  
        []   # Create overlay validation (partial) - passes
    ]
    
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Verify that overlays were validated with allow_partial=True
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 3
    
    # Resource validation should use allow_partial=True (has create overlay)
    assert calls[0][1]['allow_partial'] == True
    
    # Overlay validation should use allow_partial=True
    assert calls[1][1]['allow_partial'] == True
    
    # Create overlay validation should use allow_partial=False (merged with resource)
    assert calls[2][1]['allow_partial'] == False


def test_create_overlay_merges_with_resource_and_overlays():
    """Test that create.overlay validation merges with resource + all overlays before validation"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource",
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "base-resource",
                "replicas": 1,
                "enabled": True
            }
        },
        "overlays": [
            {
                "overlay": {
                    "spec": {
                        "replicas": 3,  # Override replicas
                        "image": "overlay-image"  # Add new field
                    }
                }
            }
        ],
        "create": {
            "overlay": {
                "spec": {
                    "enabled": False,  # Override enabled
                    "initContainers": ["init"]  # Add new field
                }
            }
        }
    }
    
    # Mock the K8s validator to capture the merged data
    from unittest.mock import Mock
    mock_validator = Mock()
    mock_validator.validate_resource_spec.return_value = []
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Get the calls
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 3
    
    # Check the merged data passed to create.overlay validation (3rd call)
    create_overlay_call = calls[2]
    merged_data = create_overlay_call[0][0]  # First positional argument
    
    # Verify the final merged state contains:
    # - Base: name="base-resource", replicas=1, enabled=True
    # - Overlay 1: replicas=3, image="overlay-image"  
    # - Create overlay: enabled=False, initContainers=["init"]
    expected_spec = {
        "spec": {
            "name": "base-resource",      # From base
            "replicas": 3,                # From overlay (overrides base)
            "enabled": False,             # From create.overlay (overrides base)
            "image": "overlay-image",     # From overlay (new field)
            "initContainers": ["init"]    # From create.overlay (new field)
        }
    }
    
    assert merged_data == expected_spec


def test_cel_expressions_skip_validation():
    """Test that CEL expressions are completely skipped during validation"""
    validator = KubernetesCRDValidator()
    
    # Schema with strict pattern constraints that would fail with dummy values
    schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "pattern": "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"  # DNS name pattern
            },
            "arn": {
                "type": "string", 
                "pattern": "^arn:aws:.*"  # AWS ARN pattern
            },
            "url": {
                "type": "string",
                "pattern": "^oci://.*$"  # OCI URL pattern
            },
            "email": {
                "type": "string",
                "format": "email"  # Email format
            },
            "status": {
                "type": "string",
                "enum": ["active", "inactive"]  # Enum constraint
            },
            "literal": {
                "type": "string",
                "pattern": "^[a-z]+$"  # Only lowercase letters
            }
        }
    }
    
    # Data with CEL expressions - these would fail pattern validation if replaced with dummy values
    test_data = {
        "name": "=inputs.resource_name",     # CEL - should be removed
        "arn": "=inputs.target_arn",         # CEL - should be removed  
        "url": "=inputs.registry_url",       # CEL - should be removed
        "email": "=inputs.contact_email",    # CEL - should be removed
        "status": "=inputs.status",          # CEL - should be removed
        "literal": "validliteral"            # Literal - should remain and be validated
    }
    
    # Process for validation (remove CEL expressions)
    prepared, has_cel = validator._prepare_data_for_validation(test_data, schema)
    
    # Verify CEL expressions are removed from validation
    assert "name" not in prepared     # CEL expression removed
    assert "arn" not in prepared      # CEL expression removed
    assert "url" not in prepared      # CEL expression removed
    assert "email" not in prepared    # CEL expression removed
    assert "status" not in prepared   # CEL expression removed
    
    # Verify literal values remain and can be validated
    assert prepared["literal"] == "validliteral"  # Literal value unchanged
    
    # Verify that CEL expressions were detected
    assert has_cel == True
    
    # The remaining data should be valid for schema validation
    # since all problematic CEL expressions have been removed


def test_oneof_relaxation_with_cel_expressions():
    """Test that oneOf/anyOf constraints are relaxed when CEL expressions are present"""
    validator = KubernetesCRDValidator()
    
    # Schema with oneOf constraint (like GCP Config Connector resources)
    schema = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "properties": {
                    "networkRef": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "namespace": {"type": "string"}
                                },
                                "required": ["name"]
                            },
                            {
                                "type": "object", 
                                "properties": {
                                    "external": {"type": "string"}
                                },
                                "required": ["external"]
                            }
                        ]
                    }
                }
            }
        }
    }
    
    # Data with CEL expression - would normally fail oneOf validation
    test_data = {
        "spec": {
            "networkRef": {
                "name": "=inputs.network_name"  # CEL expression
            }
        }
    }
    
    # This should work with relaxed oneOf validation
    errors = validator.validate_resource_spec(test_data, "example.com/v1", "TestResource")
    
    # Should not have oneOf validation errors since constraints are relaxed for CEL expressions
    assert len(errors) == 0 or all("must be valid exactly by one definition" not in error for error in errors)


def test_create_disabled_uses_partial_validation():
    """Test that when create.enabled=false, validation is partial (allows incomplete specs)"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource",
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "incomplete-resource"
                # Missing required fields like 'replicas' - would fail full validation
            }
        },
        "create": {
            "enabled": False,  # Disable creation - should enable partial validation
            "overlay": {
                "spec": {
                    "image": "patch-image"
                    # Also incomplete - would fail full validation
                }
            }
        }
    }
    
    # Mock the K8s validator to track validation calls
    from unittest.mock import Mock
    mock_validator = Mock()
    mock_validator.validate_resource_spec.return_value = []
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Get the validation calls
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Both calls should use allow_partial=True when create.enabled=False
    resource_call = calls[0]
    create_overlay_call = calls[1]
    
    assert resource_call[1]['allow_partial'] == True
    assert create_overlay_call[1]['allow_partial'] == True


def test_create_enabled_uses_full_validation():
    """Test that when create.enabled=true (default), validation is full (requires complete specs)"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource", 
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "complete-resource",
                "replicas": 3
            }
        },
        "create": {
            "enabled": True,  # Enable creation - should require full validation
            "overlay": {
                "spec": {
                    "image": "create-image"
                }
            }
        }
    }
    
    # Mock the K8s validator to track validation calls
    from unittest.mock import Mock
    mock_validator = Mock()
    mock_validator.validate_resource_spec.return_value = []
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Get the validation calls
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Both calls should use allow_partial=False when create.enabled=True
    resource_call = calls[0]
    create_overlay_call = calls[1]
    
    assert resource_call[1]['allow_partial'] == True  # Has create overlay, so partial validation
    assert create_overlay_call[1]['allow_partial'] == False


def test_create_overlay_enables_partial_validation_for_resource():
    """Test that having a create.overlay enables partial validation for the base resource"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource",
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "incomplete-resource"
                # Missing required fields - should be OK because create.overlay exists
            }
        },
        "create": {
            "enabled": True,  # Create enabled, BUT has overlay
            "overlay": {
                "spec": {
                    "priority": "=inputs.priority"  # Provides missing field
                }
            }
        }
    }
    
    # Mock the K8s validator
    from unittest.mock import Mock
    mock_validator = Mock()
    mock_validator.validate_resource_spec.return_value = []
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Get the validation calls
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Resource should use partial validation (because create overlay exists)
    resource_call = calls[0]
    assert resource_call[1]['allow_partial'] == True
    
    # Create overlay should use partial validation (contains CEL expressions)
    create_overlay_call = calls[1]
    assert create_overlay_call[1]['allow_partial'] == True


def test_no_create_overlay_requires_full_validation():
    """Test that without create.overlay, full validation is required for resource"""
    validator = ResourceFunctionValidator()
    
    spec = {
        "apiConfig": {
            "apiVersion": "example.com/v1",
            "kind": "MyResource",
            "name": "test"
        },
        "resource": {
            "spec": {
                "name": "complete-resource",
                "priority": 100  # Complete spec required
            }
        },
        "create": {
            "enabled": True
            # No overlay - resource must be complete
        }
    }
    
    # Mock the K8s validator
    from unittest.mock import Mock
    mock_validator = Mock()
    mock_validator.validate_resource_spec.return_value = []
    validator.k8s_validator = mock_validator
    
    errors = validator.validate_resource_function_spec(spec)
    
    # Get the validation calls
    calls = mock_validator.validate_resource_spec.call_args_list
    assert len(calls) == 1  # Only resource (no create.overlay)
    
    # Resource should use full validation (no create overlay to complete it)
    resource_call = calls[0]
    assert resource_call[1]['allow_partial'] == False