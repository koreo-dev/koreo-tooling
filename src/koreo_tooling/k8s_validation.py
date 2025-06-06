"""Kubernetes CRD validation for ResourceFunction specifications"""

import json
import logging
import subprocess
from copy import deepcopy

import fastjsonschema

from .cel_utils import CelExpressionDetector, CelPlaceholderGenerator
from .error_handling import ValidationError as BaseValidationError

logger = logging.getLogger("koreo.tooling.k8s_validation")


class ValidationError(BaseValidationError):
    """K8s validation error - extends base ValidationError"""
    
    def __init__(self, path: str, message: str, severity: str = "error"):
        # Convert string severity to DiagnosticSeverity
        from lsprotocol import types
        diagnostic_severity = types.DiagnosticSeverity.Error if severity == "error" else types.DiagnosticSeverity.Warning
        
        super().__init__(
            message=message,
            path=path,
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
    """Fetch CRD schema from local Kubernetes cluster"""
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
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            return None
            
        crd = json.loads(result.stdout)
        
        # Extract schema for the specific version
        for ver in crd.get("spec", {}).get("versions", []):
            if ver.get("name") == version:
                return ver.get("schema", {}).get("openAPIV3Schema")
        
        return None
        
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
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
        validator = fastjsonschema.compile(spec_schema)
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
    """Validate ResourceFunction spec with K8s CRD validation"""
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


# Public API for compatibility
def validate_resource_function_k8s(spec: dict) -> list[dict]:
    """Public API - validate ResourceFunction spec and return dict format"""
    errors = validate_resource_function(spec)
    return [{"path": e.path, "message": e.message, "severity": e.severity} for e in errors]