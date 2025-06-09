"""Kubernetes CRD validation for ResourceFunction specifications

NOTE: This module requires access to a Kubernetes cluster with installed CRDs.
If you don't have cluster access or kubectl is not available, you can:
1. Use the --skip-k8s flag in the CLI to disable CRD validation
2. Set KOREO_SKIP_K8S_VALIDATION=1 environment variable
3. Check debug logs for cluster connection issues
"""

import json
import logging
import os
import re
import subprocess
from copy import deepcopy

import fastjsonschema

from .cel_utils import CelExpressionDetector, CelPlaceholderGenerator
from .error_handling import ValidationError as BaseValidationError

logger = logging.getLogger("koreo.tooling.k8s_validation")

# Global flag to disable K8s validation
_K8S_VALIDATION_DISABLED = False

# Compiled regex for performance
_FIELD_PATTERN = re.compile(r'spec\.(\w+)')

# Cache for CRD schemas to avoid repeated kubectl calls
_CRD_SCHEMA_CACHE = {}

# Cache for compiled schema validators
_SCHEMA_VALIDATOR_CACHE = {}

def set_k8s_validation_enabled(enabled: bool) -> None:
    """Enable or disable K8s CRD validation globally"""
    global _K8S_VALIDATION_DISABLED
    _K8S_VALIDATION_DISABLED = not enabled
    if not enabled:
        logger.info("K8s CRD validation disabled")

def is_k8s_validation_enabled() -> bool:
    """Check if K8s CRD validation is enabled"""
    if _K8S_VALIDATION_DISABLED:
        return False
    
    # Check environment variable
    if os.getenv("KOREO_SKIP_K8S_VALIDATION", "").lower() in ("1", "true", "yes"):
        logger.debug("K8s validation disabled via KOREO_SKIP_K8S_VALIDATION environment variable")
        return False
    
    return True


def clear_crd_cache() -> None:
    """Clear the CRD schema cache (useful for development/testing)"""
    global _CRD_SCHEMA_CACHE, _SCHEMA_VALIDATOR_CACHE
    _CRD_SCHEMA_CACHE.clear()
    _SCHEMA_VALIDATOR_CACHE.clear()
    logger.debug("CRD schema and validator caches cleared")


class ValidationError(BaseValidationError):
    """K8s validation error - extends base ValidationError"""
    
    def __init__(self, path: str, message: str, severity: str = "error", line: int = 0, character: int = 0, end_character: int = 0):
        # Convert string severity to DiagnosticSeverity
        from lsprotocol import types
        diagnostic_severity = types.DiagnosticSeverity.Error if severity == "error" else types.DiagnosticSeverity.Warning
        
        super().__init__(
            message=message,
            path=path,
            line=line,
            character=character,
            end_character=end_character,
            severity=diagnostic_severity,
            source="koreo-k8s"
        )


# Re-export CEL utilities for backward compatibility
is_cel_expression = CelExpressionDetector.is_cel_expression
has_cel_expressions = CelExpressionDetector.has_cel_expressions


# Re-export CEL placeholder utilities for backward compatibility
replace_cel_with_placeholders = CelPlaceholderGenerator.replace_cel_with_placeholders


# Re-export CEL detection utility for backward compatibility
is_cel_related_error = CelExpressionDetector.is_cel_related_error


def get_crd_schema(api_version: str, kind: str, plural: str | None = None) -> dict | None:
    """Fetch CRD schema from local Kubernetes cluster with caching
    
    Returns None if:
    - Resource is a built-in Kubernetes resource
    - K8s validation is disabled
    - Cluster is not accessible
    - CRD doesn't exist
    """
    if not is_k8s_validation_enabled():
        return None
    
    # Create cache key
    cache_key = f"{api_version}/{kind}/{plural or 'default'}"
    if cache_key in _CRD_SCHEMA_CACHE:
        return _CRD_SCHEMA_CACHE[cache_key]
    # Skip built-in resources
    builtin_resources = {
        "v1": ["Pod", "Service", "PersistentVolume", "PersistentVolumeClaim", "ConfigMap", "Secret", "Namespace"],
        "apps/v1": ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"],
        "batch/v1": ["Job"],
        "batch/v1beta1": ["CronJob"],
        "networking.k8s.io/v1": ["Ingress", "NetworkPolicy"],
        "rbac.authorization.k8s.io/v1": ["Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"],
    }
    
    if api_version in builtin_resources and kind in builtin_resources[api_version]:
        return None
    
    # Build CRD name
    if "/" in api_version:
        group, version = api_version.split("/", 1)
    else:
        group, version = "", api_version
    
    crd_name = f"{plural or kind.lower() + 's'}.{group}" if group else (plural or kind.lower() + "s")
    
    try:
        result = subprocess.run(
            ["kubectl", "get", "crd", crd_name, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            logger.debug(f"CRD '{crd_name}' not found in cluster: {result.stderr.strip()}")
            return None
            
        crd = json.loads(result.stdout)
        
        # Extract schema for the specific version
        schema = None
        for ver in crd.get("spec", {}).get("versions", []):
            if ver.get("name") == version:
                schema = ver.get("schema", {}).get("openAPIV3Schema")
                break
        
        # Cache the result (including None)
        _CRD_SCHEMA_CACHE[cache_key] = schema
        
        if schema is None:
            logger.debug(f"Version '{version}' not found in CRD '{crd_name}'")
        
        return schema
        
    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout accessing cluster for CRD '{crd_name}' - cluster may be unreachable")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except FileNotFoundError:
        logger.debug("kubectl command not found - please install kubectl or disable K8s validation")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except json.JSONDecodeError as e:
        logger.debug(f"Invalid JSON response from kubectl for CRD '{crd_name}': {e}")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except Exception as e:
        logger.debug(f"Unexpected error accessing CRD '{crd_name}': {e}")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None


def clean_schema(schema: dict) -> dict:
    """Remove Kubernetes-specific OpenAPI extensions that fastjsonschema doesn't support"""
    cleaned = deepcopy(schema)
    
    def clean_node(node):
        if isinstance(node, dict):
            # Remove unsupported formats
            if "format" in node and node["format"] in ["int32", "int64", "byte", "date-time"]:
                del node["format"]
            
            # Remove Kubernetes extensions
            for key in list(node.keys()):
                if key.startswith("x-kubernetes-"):
                    del node[key]
            
            # Recursively clean children
            for value in node.values():
                if isinstance(value, dict | list):
                    clean_node(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict | list):
                    clean_node(item)
    
    clean_node(cleaned)
    return cleaned


def make_partial_schema(schema: dict, relax_oneof: bool = False) -> dict:
    """Remove required field constraints for partial validation"""
    partial = deepcopy(schema)
    
    def remove_constraints(node):
        if isinstance(node, dict):
            node.pop("required", None)
            
            # Also remove oneOf/anyOf when requested (for CEL expressions)
            if relax_oneof:
                node.pop("oneOf", None)
                node.pop("anyOf", None)
            
            for value in node.values():
                if isinstance(value, dict | list):
                    remove_constraints(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict | list):
                    remove_constraints(item)
    
    remove_constraints(partial)
    return partial


def validate_spec(spec_data: dict, api_version: str, kind: str, 
                  plural: str | None = None, allow_partial: bool = False) -> list[str]:
    """Validate resource spec against CRD schema"""
    schema = get_crd_schema(api_version, kind, plural)
    if not schema:
        return []
    
    # Clean and prepare schema
    schema = clean_schema(schema)
    
    # Get spec schema if it exists
    spec_schema = schema.get("properties", {}).get("spec", schema)
    
    # Check if we need partial validation
    has_cel = has_cel_expressions(spec_data)
    
    if allow_partial:
        # Use partial validation (remove required constraints)
        spec_schema = make_partial_schema(spec_schema, relax_oneof=has_cel)
    elif has_cel:
        # Only relax oneOf/anyOf for CEL expressions, keep required fields
        spec_schema = make_partial_schema(spec_schema, relax_oneof=True)
        # Reset required fields from original schema
        original_spec = schema.get("properties", {}).get("spec", schema)
        if "required" in original_spec:
            spec_schema["required"] = original_spec["required"]
    
    # Replace CEL expressions with valid placeholders
    if has_cel:
        validation_data = replace_cel_with_placeholders(spec_data, spec_schema)
    else:
        validation_data = spec_data
    
    try:
        # Use cached validator if available
        schema_key = str(hash(str(spec_schema)))
        if schema_key not in _SCHEMA_VALIDATOR_CACHE:
            _SCHEMA_VALIDATOR_CACHE[schema_key] = fastjsonschema.compile(spec_schema)
        
        validator = _SCHEMA_VALIDATOR_CACHE[schema_key]
        validator(validation_data)
        return []
    except fastjsonschema.JsonSchemaValueException as e:
        error_msg = str(e).replace("data.", "spec.").replace("data ", "spec ")
        
        # Skip errors for CEL fields
        if is_cel_related_error(error_msg, {"spec": spec_data}):
            return []
        
        return [error_msg]
    except Exception as e:
        return [f"Validation error: {e}"]


def merge_overlays(base: dict, *overlays: dict) -> dict:
    """Deep merge overlays into base resource"""
    result = deepcopy(base)
    
    for overlay in overlays:
        if not overlay:
            continue
            
        def deep_merge(target: dict, source: dict):
            for key, value in source.items():
                if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                    deep_merge(target[key], value)
                else:
                    target[key] = deepcopy(value)
        
        deep_merge(result, overlay)
    
    return result


def validate_resource_function(spec: dict) -> list[ValidationError]:
    """Validate ResourceFunction spec with K8s CRD validation
    
    If K8s validation is disabled, returns empty list.
    """
    if not is_k8s_validation_enabled():
        return []
    errors = []
    
    # Get resource type info
    api_config = spec.get("apiConfig", {})
    api_version = api_config.get("apiVersion")
    kind = api_config.get("kind")
    plural = api_config.get("plural")
    
    if not api_version or not kind:
        return errors
    
    # Check if create is enabled
    create_config = spec.get("create", {})
    create_enabled = create_config.get("enabled", True)
    create_overlay = create_config.get("overlay")
    
    # Validate main resource
    resource_spec = spec.get("resource")
    if resource_spec and "spec" in resource_spec:
        # Use partial validation only if create disabled or has create overlay
        # (CEL expressions are handled automatically in validate_spec)
        allow_partial = not create_enabled or create_overlay is not None
        
        validation_errors = validate_spec(
            resource_spec["spec"], api_version, kind, plural, allow_partial
        )
        
        for error in validation_errors:
            errors.append(ValidationError(
                path="spec.resource",
                message=f"Resource validation: {error}"
            ))
    
    # Validate overlays (always partial)
    for i, overlay_item in enumerate(spec.get("overlays", [])):
        overlay_spec = overlay_item.get("overlay", {}).get("spec")
        if overlay_spec:
            validation_errors = validate_spec(
                overlay_spec, api_version, kind, plural, allow_partial=True
            )
            
            for error in validation_errors:
                errors.append(ValidationError(
                    path=f"spec.overlays[{i}].overlay",
                    message=f"Overlay validation: {error}"
                ))
    
    # Validate create overlay (merged with resource + overlays)
    if create_overlay and resource_spec:
        # Merge resource + overlays + create overlay
        overlays = [item.get("overlay", {}) for item in spec.get("overlays", [])]
        merged = merge_overlays(resource_spec, *overlays, create_overlay)
        
        if "spec" in merged:
            use_partial = not create_enabled
            validation_errors = validate_spec(
                merged["spec"], api_version, kind, plural, use_partial
            )
            
            for error in validation_errors:
                errors.append(ValidationError(
                    path="spec.create.overlay",
                    message=f"Create overlay validation (merged): {error}"
                ))
    
    return errors


def validate_embedded_resource(resource: dict, path_prefix: str = "", yaml_lines: list[str] = None) -> list[ValidationError]:
    """Validate an embedded Kubernetes resource against its CRD
    
    Args:
        resource: The Kubernetes resource dictionary
        path_prefix: Path prefix for error reporting (e.g., "spec.currentResource")
        yaml_lines: Original YAML file lines for better position tracking
    
    Returns:
        List of validation errors
    """
    if not is_k8s_validation_enabled():
        return []
    
    errors = []
    
    # Extract resource metadata
    api_version = resource.get("apiVersion")
    kind = resource.get("kind")
    spec = resource.get("spec")
    
    if not api_version or not kind:
        # Not a valid Kubernetes resource - skip validation
        logger.debug(f"Skipping embedded resource validation - missing apiVersion or kind: {path_prefix}")
        return errors
    
    if not spec:
        # Resource has no spec to validate
        logger.debug(f"Skipping embedded resource validation - no spec: {path_prefix}")
        return errors
    
    logger.debug(f"Validating embedded resource {api_version}/{kind} at {path_prefix}")
    
    # Validate the resource spec against its CRD
    # Note: We don't use allow_partial=True here because embedded resources
    # in tests should be complete and don't contain CEL expressions
    validation_errors = validate_spec(spec, api_version, kind, allow_partial=False)
    
    for error in validation_errors:
        error_path = f"{path_prefix}.spec" if path_prefix else "spec"
        
        # Try to find more specific line number and character position using yaml_lines
        line_number = 0
        character_pos = 0
        end_character_pos = 0
        
        if yaml_lines:
            from .yaml_utils import YamlProcessor
            
            # Extract specific field from error message (e.g., "spec.cidrBlock must be string" -> "cidrBlock")
            field_match = _FIELD_PATTERN.search(error)
            if field_match:
                field_name = field_match.group(1)
                # Build path to the specific field (e.g., "spec.testCases[0].expectResource.spec.cidrBlock")
                specific_field_path = f"{path_prefix}.spec.{field_name}" if path_prefix else f"spec.{field_name}"
                line_number = YamlProcessor.find_line_for_path(yaml_lines, specific_field_path) or 0
                if line_number == 0:
                    # Fallback to just the field name within the resource
                    line_number = YamlProcessor.find_line_for_path(yaml_lines, field_name) or 0
                
                # If we found the line, also find the column position of the field
                if 0 < line_number < len(yaml_lines):
                    line_content = yaml_lines[line_number]
                    # Find the column position of the field name
                    field_pattern = f"{field_name}:"
                    field_pos = line_content.find(field_pattern)
                    if field_pos >= 0:
                        character_pos = field_pos
                        # Calculate end position more precisely - just the value, not to end of line
                        value_start = field_pos + len(field_pattern)
                        # Skip whitespace after colon
                        while value_start < len(line_content) and line_content[value_start] in ' \t':
                            value_start += 1
                        
                        # Find the end of the value (before any trailing spaces or comments)
                        value_end = value_start
                        while value_end < len(line_content) and line_content[value_end] not in ' \t\n\r#':
                            value_end += 1
                        
                        # End position should include the entire field:value pair
                        end_character_pos = value_end
                    else:
                        # If field not found on line, highlight a reasonable portion
                        character_pos = 0
                        end_character_pos = min(len(line_content.rstrip()), 40)  # Limit to avoid huge highlights
            
            # If still no specific line found, fall back to the resource container
            if line_number == 0:
                line_number = YamlProcessor.find_line_for_path(yaml_lines, path_prefix) or 0
        
        # Create error with character positions
        errors.append(ValidationError(
            path=error_path,
            message=f"Embedded {kind} validation: {error}",
            severity="error",
            line=line_number,
            character=character_pos,
            end_character=end_character_pos if end_character_pos > character_pos else character_pos + 10
        ))
    
    return errors


# Public API for compatibility
def validate_resource_function_k8s(spec: dict) -> list[dict]:
    """Public API - validate ResourceFunction spec and return dict format"""
    errors = validate_resource_function(spec)
    return [{"path": e.path, "message": e.message, "severity": e.severity} for e in errors]