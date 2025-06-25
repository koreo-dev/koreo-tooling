"""Kubernetes CRD validation for ResourceFunction specifications

NOTE: This module requires access to a Kubernetes cluster with installed CRDs.
If you don't have cluster access or kubectl is not available, you can:
1. Set KOREO_SKIP_K8S_VALIDATION=1 environment variable
2. Check debug logs for cluster connection issues
"""

import json
import logging
import os
import subprocess
from copy import deepcopy

from .cel_utils import (
    has_cel_expressions,
    replace_cel_with_placeholders,
)
from .error_handling import ValidationError

logger = logging.getLogger("koreo.tooling.k8s_validation")

# Global flag to disable K8s validation
_K8S_VALIDATION_DISABLED = False


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
    if os.getenv("KOREO_SKIP_K8S_VALIDATION", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.debug(
            "K8s validation disabled via KOREO_SKIP_K8S_VALIDATION environment variable"  # noqa: E501
        )
        return False

    return True


def clear_crd_cache() -> None:
    """Clear the CRD schema cache (useful for development/testing)"""
    global _CRD_SCHEMA_CACHE, _SCHEMA_VALIDATOR_CACHE
    _CRD_SCHEMA_CACHE.clear()
    _SCHEMA_VALIDATOR_CACHE.clear()
    logger.debug("CRD schema and validator caches cleared")


def get_crd_schema(
    api_version: str, kind: str, plural: str | None = None
) -> dict | None:
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
        "v1": [
            "Pod",
            "Service",
            "PersistentVolume",
            "PersistentVolumeClaim",
            "ConfigMap",
            "Secret",
            "Namespace",
        ],
        "apps/v1": ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"],
        "batch/v1": ["Job"],
        "batch/v1beta1": ["CronJob"],
        "networking.k8s.io/v1": ["Ingress", "NetworkPolicy"],
        "rbac.authorization.k8s.io/v1": [
            "Role",
            "RoleBinding",
            "ClusterRole",
            "ClusterRoleBinding",
        ],
    }

    if (
        api_version in builtin_resources
        and kind in builtin_resources[api_version]
    ):
        return None

    # Build CRD name
    if "/" in api_version:
        group, version = api_version.split("/", 1)
    else:
        group, version = "", api_version

    crd_name = (
        f"{plural or kind.lower() + 's'}.{group}"
        if group
        else (plural or kind.lower() + "s")
    )

    try:
        result = subprocess.run(
            ["kubectl", "get", "crd", crd_name, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug(
                f"CRD '{crd_name}' not found in cluster: {result.stderr.strip()}"  # noqa: E501
            )
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
        logger.debug(
            f"Timeout accessing cluster for CRD '{crd_name}' - cluster may be unreachable"  # noqa: E501
        )
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except FileNotFoundError:
        logger.debug("kubectl command not found - please install kubectl")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except json.JSONDecodeError as e:
        logger.debug(
            f"Invalid JSON response from kubectl for CRD '{crd_name}': {e}"
        )
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None
    except Exception as e:
        logger.debug(f"Unexpected error accessing CRD '{crd_name}': {e}")
        _CRD_SCHEMA_CACHE[cache_key] = None
        return None


def clean_schema(schema: dict) -> dict:
    cleaned = deepcopy(schema)

    def clean_node(node):
        if isinstance(node, dict):
            # Remove unsupported formats
            if "format" in node and node["format"] in [
                "int32",
                "int64",
                "byte",
                "date-time",
            ]:
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


def validate_spec(
    spec_data: dict,
    api_version: str,
    kind: str,
    plural: str | None = None,
    allow_partial: bool = False,
) -> list[str]:
    """Validate resource spec against CRD schema (type checking only).

    This function performs type validation to ensure fields have the correct
    data types (string, integer, boolean, etc.) according to the CRD schema.

    NOTE: This does NOT validate required fields. This is intentional because:
    - ResourceFunctions often use overlays that provide missing fields
    - CEL expressions may compute values dynamically
    - Partial specs are common in Koreo workflows

    For full validation including required fields, use kubectl dry-run.
    """
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

    # Custom approach to collect multiple errors by validating individual fields
    errors = []

    def validate_field(field_path, field_value, field_schema):
        """Validate a single field and collect errors"""
        if not isinstance(field_schema, dict):
            return

        # Check type validation
        expected_type = field_schema.get("type")
        if expected_type:
            if expected_type == "integer" and not isinstance(field_value, int):
                if isinstance(field_value, str):
                    errors.append(f"spec.{field_path} must be integer")
            elif expected_type == "number" and not isinstance(
                field_value, int | float
            ):
                if isinstance(field_value, str):
                    errors.append(f"spec.{field_path} must be number")
            elif expected_type == "string" and not isinstance(field_value, str):
                errors.append(f"spec.{field_path} must be string")
            elif expected_type == "boolean" and not isinstance(
                field_value, bool
            ):
                errors.append(f"spec.{field_path} must be boolean")

        # Recurse into objects
        if isinstance(field_value, dict) and "properties" in field_schema:
            for prop_name, prop_value in field_value.items():
                prop_schema = field_schema["properties"].get(prop_name, {})
                validate_field(
                    f"{field_path}.{prop_name}", prop_value, prop_schema
                )

    # Start validation from root
    if "properties" in spec_schema:
        for field_name, field_value in validation_data.items():
            field_schema = spec_schema["properties"].get(field_name, {})
            validate_field(field_name, field_value, field_schema)

    # Skip errors for CEL fields - just return all errors for simplicity
    return errors


def merge_overlays(base: dict, *overlays: dict) -> dict:
    """Deep merge overlays into base resource"""
    result = deepcopy(base)

    for overlay in overlays:
        if not overlay:
            continue

        def deep_merge(target: dict, source: dict):
            for key, value in source.items():
                if (
                    key in target
                    and isinstance(target[key], dict)
                    and isinstance(value, dict)
                ):
                    deep_merge(target[key], value)
                else:
                    target[key] = deepcopy(value)

        deep_merge(result, overlay)

    return result


def validate_resource_function(spec: dict) -> list[ValidationError]:
    """Validate ResourceFunction spec with K8s CRD validation.

    Performs type validation on ResourceFunction specs against the CRD schemas.
    This validates that fields have correct data types but does NOT check for
    required fields, as ResourceFunctions commonly use overlays and CEL
    expressions.

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
            errors.append(
                ValidationError(
                    path="spec.resource",
                    message=f"Resource validation: {error}",
                )
            )

    # Validate overlays (always partial)
    for i, overlay_item in enumerate(spec.get("overlays", [])):
        overlay_spec = overlay_item.get("overlay", {}).get("spec")
        if overlay_spec:
            validation_errors = validate_spec(
                overlay_spec, api_version, kind, plural, allow_partial=True
            )

            for error in validation_errors:
                errors.append(
                    ValidationError(
                        path=f"spec.overlays[{i}].overlay",
                        message=f"Overlay validation: {error}",
                    )
                )

    # Validate create overlay (merged with resource + overlays)
    if create_overlay and resource_spec:
        # Merge resource + overlays + create overlay
        overlays = [
            item.get("overlay", {}) for item in spec.get("overlays", [])
        ]
        merged = merge_overlays(resource_spec, *overlays, create_overlay)

        if "spec" in merged:
            use_partial = not create_enabled
            validation_errors = validate_spec(
                merged["spec"], api_version, kind, plural, use_partial
            )

            for error in validation_errors:
                errors.append(
                    ValidationError(
                        path="spec.create.overlay",
                        message=f"Create overlay validation (merged): {error}",
                    )
                )

    return errors


def validate_resource_function_k8s(spec: dict) -> list[dict]:
    """Public API - validate ResourceFunction spec and return dict format"""
    errors = validate_resource_function(spec)
    return [
        {"path": e.path, "message": e.message, "severity": e.severity}
        for e in errors
    ]
