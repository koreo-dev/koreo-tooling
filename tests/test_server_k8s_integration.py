"""Tests for K8s validation integration in the language server."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from lsprotocol import types

from koreo_tooling.server import _validate_k8s_resources, _find_field_position
from koreo_tooling.langserver.fileprocessor import SemanticRangeIndex
from koreo_tooling.error_handling import ValidationError


class TestServerK8sIntegration:
    """Test suite for K8s validation integration in the language server."""

    def test_validate_k8s_resources_with_errors(self):
        """Test _validate_k8s_resources function detects and converts errors."""
        # Mock semantic range index
        range_info = types.Range(
            start=types.Position(line=2, character=0),
            end=types.Position(line=5, character=20)
        )
        
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=range_info,
                version=None
            )
        ]

        # Mock cache response
        mock_cached = Mock()
        mock_cached.resource = Mock()
        mock_cached.spec = {
            "apiConfig": {
                "apiVersion": "aws.konfigurate.realkinetic.com/v1beta1",
                "kind": "AwsEnvironment",
            },
            "resource": {
                "spec": {
                    "autoScalingGroup": {
                        "maxReplicas": "invalid_string"
                    }
                }
            }
        }

        # Mock validation errors
        validation_errors = [
            ValidationError(
                message="spec.autoScalingGroup.maxReplicas must be integer",
                path="spec.resource",
                line=0,
                character=0
            )
        ]

        with patch("koreo_tooling.server.cache.get_resource_system_data_from_cache") as mock_cache, \
             patch("koreo_tooling.k8s_validation.validate_resource_function") as mock_validate, \
             patch("koreo_tooling.k8s_validation.is_k8s_validation_enabled") as mock_enabled:
            
            mock_cache.return_value = mock_cached
            mock_validate.return_value = validation_errors
            mock_enabled.return_value = True

            diagnostics = _validate_k8s_resources(semantic_range_index)

            assert len(diagnostics) >= 1
            
            # Find the validation diagnostic
            validation_diagnostic = None
            for diagnostic in diagnostics:
                if "K8s validation:" in diagnostic.message:
                    validation_diagnostic = diagnostic
                    break
            
            assert validation_diagnostic is not None
            assert "spec.autoScalingGroup.maxReplicas must be integer" in validation_diagnostic.message
            assert validation_diagnostic.severity == types.DiagnosticSeverity.Error
            assert validation_diagnostic.source == "k8s-validation"

    def test_validate_k8s_resources_disabled(self):
        """Test _validate_k8s_resources returns empty when disabled."""
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=types.Range(
                    start=types.Position(line=2, character=0),
                    end=types.Position(line=5, character=20)
                ),
                version=None
            )
        ]

        with patch("koreo_tooling.k8s_validation.is_k8s_validation_enabled") as mock_enabled:
            mock_enabled.return_value = False
            
            diagnostics = _validate_k8s_resources(semantic_range_index)
            assert len(diagnostics) == 0

    def test_validate_k8s_resources_no_cache(self):
        """Test _validate_k8s_resources handles missing cache gracefully."""
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=types.Range(
                    start=types.Position(line=2, character=0),
                    end=types.Position(line=5, character=20)
                ),
                version=None
            )
        ]

        with patch("koreo_tooling.server.cache.get_resource_system_data_from_cache") as mock_cache, \
             patch("koreo_tooling.k8s_validation.is_k8s_validation_enabled") as mock_enabled:
            
            mock_cache.return_value = None  # No cached resource
            mock_enabled.return_value = True
            
            diagnostics = _validate_k8s_resources(semantic_range_index)
            assert len(diagnostics) == 0

    def test_find_field_position_exact_match(self):
        """Test _find_field_position finds exact field location."""
        # Mock semantic range index
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=types.Range(
                    start=types.Position(line=2, character=0),
                    end=types.Position(line=5, character=20)
                ),
                version=None
            )
        ]
        
        default_range = types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=10)
        )

        # Mock document with field content
        mock_doc = Mock()
        mock_doc.lines = [
            "apiVersion: koreo.dev/v1beta1",
            "kind: ResourceFunction",
            "metadata:",
            "  name: test-function",
            "spec:",
            "  resource:",
            "    spec:",
            "      autoScalingGroup:",
            "        maxReplicas: \"invalid\"",  # Line 8
            "        minReplicas: 1"
        ]

        # Mock the server module properly
        mock_server = Mock()
        mock_server.workspace.get_text_document.return_value = mock_doc
        
        with patch("koreo_tooling.server.server", mock_server):
            
            result_range = _find_field_position(
                semantic_range_index, 
                "test-function", 
                "spec.autoScalingGroup.maxReplicas",
                default_range
            )
            
            # Should find the exact line and position of maxReplicas
            assert result_range.start.line == 8
            assert result_range.start.character == 8  # Position of "maxReplicas"
            assert result_range.end.character == 8 + len("maxReplicas")

    def test_find_field_position_fallback_to_spec(self):
        """Test _find_field_position falls back to spec section when field not found."""
        # Mock semantic range index with def range
        def_range = types.Range(
            start=types.Position(line=2, character=0),
            end=types.Position(line=5, character=20)
        )
        
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=def_range,
                version=None
            )
        ]
        
        default_range = types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=10)
        )

        # Mock document without the specific field
        mock_doc = Mock()
        mock_doc.lines = [
            "apiVersion: koreo.dev/v1beta1",
            "kind: ResourceFunction",
            "metadata:",
            "  name: test-function",
            "spec:",
            "  resource:",
            "    spec:",
            "      # field not found here"
        ]

        # Mock the server module properly
        mock_server = Mock()
        mock_server.workspace.get_text_document.return_value = mock_doc
        
        with patch("koreo_tooling.server.server", mock_server):
            
            result_range = _find_field_position(
                semantic_range_index, 
                "test-function", 
                "spec.autoScalingGroup.nonexistentField",
                default_range
            )
            
            # Should fall back to approximate spec location (def_range.start.line + 5)
            expected_line = def_range.start.line + 5  # Line 7
            assert result_range.start.line == expected_line
            assert result_range.start.character == 0

    def test_find_field_position_no_semantic_info(self):
        """Test _find_field_position returns default when no semantic info available."""
        semantic_range_index = []  # Empty
        
        default_range = types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=10)
        )
        
        result_range = _find_field_position(
            semantic_range_index, 
            "test-function", 
            "spec.autoScalingGroup.maxReplicas",
            default_range
        )
        
        # Should return the default range unchanged
        assert result_range == default_range

    def test_find_field_position_handles_exception(self):
        """Test _find_field_position handles exceptions gracefully."""
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=types.Range(
                    start=types.Position(line=2, character=0),
                    end=types.Position(line=5, character=20)
                ),
                version=None
            )
        ]
        
        default_range = types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=10)
        )

        # Mock the server to raise an exception
        mock_server = Mock()
        mock_server.workspace.get_text_document.side_effect = Exception("Document not found")
        
        with patch("koreo_tooling.server.server", mock_server):
            
            result_range = _find_field_position(
                semantic_range_index, 
                "test-function", 
                "spec.autoScalingGroup.maxReplicas",
                default_range
            )
            
            # Should fall back to spec approximation since file search failed
            assert result_range.start.line == 7  # 2 + 5
            assert result_range.start.character == 0

    def test_multiple_validation_errors_create_multiple_diagnostics(self):
        """Test that multiple validation errors create multiple diagnostics."""
        range_info = types.Range(
            start=types.Position(line=2, character=0),
            end=types.Position(line=5, character=20)
        )
        
        semantic_range_index = [
            SemanticRangeIndex(
                uri="file:///test.yaml",
                name="ResourceFunction:test-function:def",
                range=range_info,
                version=None
            )
        ]

        mock_cached = Mock()
        mock_cached.resource = Mock()
        mock_cached.spec = {"apiConfig": {}, "resource": {"spec": {}}}

        # Multiple validation errors
        validation_errors = [
            ValidationError(
                message="spec.autoScalingGroup.maxReplicas must be integer",
                path="spec.resource",
            ),
            ValidationError(
                message="spec.autoScalingGroup.minReplicas must be integer", 
                path="spec.resource",
            )
        ]

        with patch("koreo_tooling.server.cache.get_resource_system_data_from_cache") as mock_cache, \
             patch("koreo_tooling.k8s_validation.validate_resource_function") as mock_validate, \
             patch("koreo_tooling.k8s_validation.is_k8s_validation_enabled") as mock_enabled:
            
            mock_cache.return_value = mock_cached
            mock_validate.return_value = validation_errors
            mock_enabled.return_value = True

            diagnostics = _validate_k8s_resources(semantic_range_index)

            # Should have diagnostics for both validation errors
            validation_diagnostics = [d for d in diagnostics if "K8s validation:" in d.message]
            assert len(validation_diagnostics) == 2
            
            messages = [d.message for d in validation_diagnostics]
            assert any("maxReplicas must be integer" in msg for msg in messages)
            assert any("minReplicas must be integer" in msg for msg in messages)