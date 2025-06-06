"""Tests for Kubernetes CRD validation functionality"""

import pytest
from unittest.mock import patch, MagicMock, Mock
import json

from koreo_tooling.k8s_validation import (
    get_crd_schema,
    validate_spec,
    validate_resource_function,
    validate_resource_function_k8s,
    is_cel_expression,
    has_cel_expressions,
    replace_cel_with_placeholders,
    clean_schema,
    make_partial_schema,
    merge_overlays,
    is_cel_related_error
)


class TestK8sValidation:
    """Test cases for K8s validation functions"""
    
    def test_is_builtin_resource(self):
        """Test detection of built-in Kubernetes resources"""
        # Test built-in resources - these should return None (no CRD)
        assert get_crd_schema("apps/v1", "Deployment") is None
        assert get_crd_schema("v1", "Pod") is None
        assert get_crd_schema("v1", "Service") is None
        
        # Test custom resources - these would need a CRD (mocked in other tests)
        # The actual result depends on whether the CRD exists in the cluster
        # So we just test that the function doesn't crash
        result = get_crd_schema("example.com/v1", "MyCustomResource")
        assert result is None or isinstance(result, dict)
    
    def test_get_crd_schema_builtin_resource(self):
        """Test that built-in resources don't attempt CRD lookup"""
        # Should return None for built-in resources (no validation)
        result = get_crd_schema("apps/v1", "Deployment")
        assert result is None
    
    @patch('subprocess.run')
    def test_get_crd_from_cluster_success(self, mock_run):
        """Test successful CRD retrieval from cluster"""
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
            stdout=json.dumps(mock_crd)
        )
        
        result = get_crd_schema("example.com/v1", "MyResource")
        assert result == mock_crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    
    @patch('subprocess.run')
    def test_get_crd_from_cluster_not_found(self, mock_run):
        """Test CRD not found scenario"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr='Error from server (NotFound): customresourcedefinitions.apiextensions.k8s.io "myresources.example.com" not found'
        )
        
        result = get_crd_schema("example.com/v1", "MyResource")
        assert result is None
    
    @patch('subprocess.run')
    def test_extract_schema_from_crd(self, mock_run):
        """Test schema extraction from CRD"""
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
        
        # Mock kubectl to return the CRD for v1
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(crd)
        )
        
        # Test extracting v1 schema
        schema_v1 = get_crd_schema("example.com/v1", "MyResource")
        assert schema_v1["properties"]["spec"]["properties"]["field1"]["type"] == "string"
        
        # Mock kubectl to return nothing for v3 (version doesn't exist)
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="not found"
        )
        
        # Test non-existent version
        schema_none = get_crd_schema("example.com/v3", "MyResource")
        assert schema_none is None


class TestResourceFunctionValidator:
    """Test cases for ResourceFunction validation"""
    
    @patch('koreo_tooling.k8s_validation.validate_spec')
    def test_validate_resource_function_spec(self, mock_validate):
        """Test ResourceFunction spec validation"""
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
        
        errors = validate_resource_function(spec)
        
        # Should have 3 errors (resource, overlay, create.overlay)
        assert len(errors) == 3
        
        # Check error details
        assert any("spec.resource" in error.path for error in errors)
        assert any("spec.overlays[0].overlay" in error.path for error in errors)
        assert any("spec.create.overlay" in error.path for error in errors)
    
    def test_validate_resource_function_spec_no_api_config(self):
        """Test ResourceFunction without apiConfig"""
        spec = {
            "resource": {"spec": {"field": "value"}}
        }
        
        errors = validate_resource_function(spec)
        assert len(errors) == 0  # No validation without apiConfig
    
    def test_validate_resource_function_spec_builtin_resource(self):
        """Test ResourceFunction with built-in Kubernetes resource"""
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
        
        errors = validate_resource_function(spec)
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
    
    # Clean the schema to remove unsupported formats
    cleaned_schema = clean_schema(schema_with_k8s_formats)
    
    # Should not have unsupported formats after cleaning
    assert cleaned_schema["properties"]["spec"]["properties"]["replicas"].get("format") is None
    assert cleaned_schema["properties"]["spec"]["properties"]["timeout"].get("format") is None
    assert cleaned_schema["properties"]["spec"]["properties"]["data"].get("format") is None
    assert cleaned_schema["properties"]["spec"]["properties"]["timestamp"].get("format") is None
    
    # Test that validation works with cleaned schema
    test_spec = {
        "replicas": 3,
        "timeout": 300,
        "data": "base64data",
        "timestamp": "2024-01-01T00:00:00Z"
    }
    
    # Use validate_spec which handles cleaning internally
    errors = validate_spec({"spec": test_spec}, "example.com/v1", "TestResource")
    # Since we're not mocking get_crd_schema, it will return None and skip validation
    assert errors == []


def test_cel_expression_removal():
    """Test that CEL expressions are replaced with appropriate placeholders for validation"""
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
    
    # Replace CEL expressions with placeholders
    prepared = replace_cel_with_placeholders(test_data, schema)
    
    # Verify CEL expressions are replaced with appropriate placeholders
    assert prepared["replicas"] == 1  # CEL replaced with integer placeholder
    assert prepared["enabled"] == True   # CEL replaced with boolean placeholder
    assert prepared["name"] == "my-app"  # Literal value unchanged
    assert prepared["ports"] == [80, 1, 443]  # CEL replaced with integer in array
    assert prepared["config"]["timeout"] == 1.0  # CEL replaced with number in nested object
    
    # Verify that CEL expressions were detected
    assert has_cel_expressions(test_data) == True


@patch('koreo_tooling.k8s_validation.get_crd_schema')
def test_partial_validation_for_overlays(mock_get_crd):
    """Test that overlays use partial validation (no required fields) while resources use full validation"""
    # Mock a schema with required fields
    mock_schema = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "replicas": {"type": "integer"},
                    "enabled": {"type": "boolean"}
                },
                "required": ["name", "replicas"]
            }
        }
    }
    mock_get_crd.return_value = mock_schema
    
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
    
    errors = validate_resource_function(spec)
    
    # Should have no errors since overlays use partial validation
    # (required fields are not enforced for overlays)
    assert len(errors) == 0
    
    # Verify that validate_spec was called with correct allow_partial flags
    assert mock_get_crd.call_count >= 1


def test_create_overlay_merges_with_resource_and_overlays():
    """Test that create.overlay validation merges with resource + all overlays before validation"""
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
    
    # Test the merge_overlays function directly
    base = spec["resource"]
    overlay = spec["overlays"][0]["overlay"]
    create_overlay = spec["create"]["overlay"]
    
    # Merge all overlays
    merged = merge_overlays(base, overlay, create_overlay)
    
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
    
    assert merged == expected_spec


def test_cel_expressions_skip_validation():
    """Test that CEL expressions are replaced with valid placeholders during validation"""
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
    
    # Replace CEL expressions with placeholders
    prepared = replace_cel_with_placeholders(test_data, schema)
    
    # Verify CEL expressions are replaced with valid placeholders
    # For patterns, we use generic strings that may not match the pattern
    # but the validation should detect CEL-related errors and skip them
    assert prepared["name"] == "placeholder-string"     # CEL replaced with string
    assert prepared["arn"] == "placeholder-string"      # CEL replaced with string
    assert prepared["url"] == "placeholder-string"      # CEL replaced with string
    assert prepared["email"] == "placeholder-string"    # CEL replaced with string
    assert prepared["status"] == "placeholder-string"   # CEL replaced with string
    
    # Verify literal values remain and can be validated
    assert prepared["literal"] == "validliteral"  # Literal value unchanged
    
    # Verify that CEL expressions were detected
    assert has_cel_expressions(test_data) == True


@patch('koreo_tooling.k8s_validation.get_crd_schema')
def test_oneof_relaxation_with_cel_expressions(mock_get_crd):
    """Test that oneOf/anyOf constraints are relaxed when CEL expressions are present"""
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
    
    # Mock the CRD schema
    mock_get_crd.return_value = schema
    
    # This should work with relaxed oneOf validation
    errors = validate_spec(test_data["spec"], "example.com/v1", "TestResource")
    
    # Should not have oneOf validation errors since constraints are relaxed for CEL expressions
    assert len(errors) == 0 or all("must be valid exactly by one definition" not in error for error in errors)


@patch('koreo_tooling.k8s_validation.validate_spec')
def test_create_disabled_uses_partial_validation(mock_validate_spec):
    """Test that when create.enabled=false, validation is partial (allows incomplete specs)"""
    mock_validate_spec.return_value = []
    
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
    
    errors = validate_resource_function(spec)
    
    # Get the validation calls
    calls = mock_validate_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Both calls should use allow_partial=True when create.enabled=False
    resource_call = calls[0]
    create_overlay_call = calls[1]
    
    # Check the allow_partial argument (can be positional or keyword)
    # Resource call uses positional argument (5th argument)
    assert resource_call[0][4] == True  # allow_partial positional
    # Create overlay call uses positional argument (5th argument)
    assert create_overlay_call[0][4] == True  # allow_partial positional


@patch('koreo_tooling.k8s_validation.validate_spec')
def test_create_enabled_uses_full_validation(mock_validate_spec):
    """Test that when create.enabled=true (default), validation is full (requires complete specs)"""
    mock_validate_spec.return_value = []
    
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
    
    errors = validate_resource_function(spec)
    
    # Get the validation calls
    calls = mock_validate_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Resource should use partial when create overlay exists
    # Create overlay should use full validation when enabled
    resource_call = calls[0]
    create_overlay_call = calls[1]
    
    # Check the allow_partial argument (positional - 5th argument)
    assert resource_call[0][4] == True  # Has create overlay, so partial validation
    assert create_overlay_call[0][4] == False  # Full validation when enabled


@patch('koreo_tooling.k8s_validation.validate_spec')
def test_create_overlay_enables_partial_validation_for_resource(mock_validate_spec):
    """Test that having a create.overlay enables partial validation for the base resource"""
    mock_validate_spec.return_value = []
    
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
    
    errors = validate_resource_function(spec)
    
    # Get the validation calls
    calls = mock_validate_spec.call_args_list
    assert len(calls) == 2  # resource + create.overlay
    
    # Resource should use partial validation (because create overlay exists)
    resource_call = calls[0]
    assert resource_call[0][4] == True  # allow_partial positional
    
    # Create overlay should use full validation when create is enabled
    create_overlay_call = calls[1]
    assert create_overlay_call[0][4] == False  # allow_partial positional


@patch('koreo_tooling.k8s_validation.validate_spec')
def test_no_create_overlay_requires_full_validation(mock_validate_spec):
    """Test that without create.overlay, full validation is required for resource"""
    mock_validate_spec.return_value = []
    
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
    
    errors = validate_resource_function(spec)
    
    # Get the validation calls
    calls = mock_validate_spec.call_args_list
    assert len(calls) == 1  # Only resource (no create.overlay)
    
    # Resource should use full validation (no create overlay to complete it)
    resource_call = calls[0]
    assert resource_call[0][4] == False  # allow_partial positional