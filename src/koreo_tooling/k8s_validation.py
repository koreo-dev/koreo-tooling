"""Kubernetes CRD validation for ResourceFunction specifications"""

import json
import logging
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

import fastjsonschema

logger = logging.getLogger("koreo.tooling.k8s_validation")


@dataclass
class ValidationError:
    path: str
    message: str
    severity: str = "error"


def is_cel_expression(value: Any) -> bool:
    """Check if a value is a CEL expression (string starting with '=' or containing CEL in multiline)"""
    if not isinstance(value, str):
        return False
    
    # Direct CEL expression
    if value.startswith("="):
        return True
    
    # Multi-line string containing CEL expression
    # Check if it's a multi-line string that contains CEL
    if "\n" in value and any(line.strip().startswith("=") for line in value.split("\n")):
        return True
    
    # Single line that starts with = after whitespace (YAML folded/literal blocks)
    stripped = value.strip()
    if stripped.startswith("="):
        return True
    
    return False


def has_cel_expressions(obj: Any) -> bool:
    """Recursively check if an object contains any CEL expressions"""
    if is_cel_expression(obj):
        return True
    if isinstance(obj, dict):
        return any(has_cel_expressions(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_cel_expressions(item) for item in obj)
    return False


def get_placeholder_for_type(field_schema: dict) -> any:
    """Get appropriate placeholder value based on schema type"""
    field_type = field_schema.get("type")
    
    if field_type == "string":
        return "placeholder-string"
    elif field_type == "integer":
        return 1
    elif field_type == "number":
        return 1.0
    elif field_type == "boolean":
        return True
    elif field_type == "array":
        # For arrays, create a placeholder based on items schema
        items_schema = field_schema.get("items", {})
        if items_schema:
            placeholder_item = get_placeholder_for_type(items_schema)
            return [placeholder_item] if placeholder_item is not None else []
        return []
    elif field_type == "object":
        return {}
    else:
        # Try to infer from common field names if type is not specified
        return "placeholder-string"


def replace_cel_with_placeholders(data: dict, schema: dict) -> dict:
    """Replace CEL expressions with valid placeholder values based on schema types"""
    result = {}
    
    # Get properties from schema
    properties = schema.get("properties", {})
    
    for key, value in data.items():
        if is_cel_expression(value):
            # Replace CEL expression with placeholder based on expected type
            field_schema = properties.get(key, {})
            
            # Special handling for common Kubernetes field names when schema type is missing
            if not field_schema.get("type"):
                if key == "env":
                    # Kubernetes env is always an array of objects
                    result[key] = [{"name": "PLACEHOLDER", "value": "placeholder"}]
                elif key in ["ports", "containers", "volumes", "volumeMounts"]:
                    # These are typically arrays
                    result[key] = []
                elif key in ["labels", "annotations", "selector"]:
                    # These are typically objects
                    result[key] = {}
                else:
                    result[key] = get_placeholder_for_type(field_schema)
            else:
                result[key] = get_placeholder_for_type(field_schema)
        elif isinstance(value, dict):
            # Recursively process nested objects
            field_schema = properties.get(key, {})
            if "properties" in field_schema:
                result[key] = replace_cel_with_placeholders(value, field_schema)
            else:
                result[key] = replace_cel_with_placeholders(value, {})
        elif isinstance(value, list):
            # Process lists
            cleaned_list = []
            list_schema = properties.get(key, {})
            items_schema = list_schema.get("items", {})
            
            for item in value:
                if is_cel_expression(item):
                    # Use appropriate placeholder for list items
                    if items_schema:
                        placeholder = get_placeholder_for_type(items_schema)
                        cleaned_list.append(placeholder)
                    else:
                        cleaned_list.append("placeholder-string")
                elif isinstance(item, dict):
                    if items_schema and "properties" in items_schema:
                        cleaned_list.append(replace_cel_with_placeholders(item, items_schema))
                    else:
                        cleaned_list.append(replace_cel_with_placeholders(item, {}))
                else:
                    cleaned_list.append(item)
            result[key] = cleaned_list
        else:
            result[key] = value
    
    return result


def is_cel_related_error(error_msg: str, original_data: dict) -> bool:
    """Check if validation error is about a field that contains CEL expressions"""
    # Extract field path from error like "spec.ipCidrRange must contain..."
    match = re.match(r"spec\.([^\s]+)", error_msg)
    if not match:
        return False
    
    field_path = match.group(1)
    current = original_data.get("spec", original_data)
    
    # Navigate to the field
    for part in field_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    
    return is_cel_expression(current)


def get_crd_schema(api_version: str, kind: str, plural: Optional[str] = None) -> Optional[dict]:
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
                if isinstance(value, (dict, list)):
                    clean_node(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
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
                if isinstance(value, (dict, list)):
                    remove_constraints(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    remove_constraints(item)
    
    remove_constraints(partial)
    return partial


def validate_spec(spec_data: dict, api_version: str, kind: str, 
                  plural: Optional[str] = None, allow_partial: bool = False) -> list[str]:
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