"""Kubernetes CRD-based validation for ResourceFunction resource specifications"""

import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

import yaml
import fastjsonschema
from lsprotocol import types

logger = logging.getLogger("koreo.tooling.k8s_validation")

class KubernetesCRDValidator:
    """Validator for Kubernetes resources using CRDs from local cluster"""
    
    def __init__(self):
        self.crd_schemas: Dict[str, dict] = {}
        self.compiled_validators: Dict[str, Any] = {}
        self.full_schemas: Dict[str, dict] = {}  # Cache for full schemas
        
        # Built-in Kubernetes resource types that don't have CRDs
        self.builtin_resources = {
            "v1": ["Pod", "Service", "PersistentVolume", "PersistentVolumeClaim", "ConfigMap", "Secret", "Namespace"],
            "apps/v1": ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"],
            "batch/v1": ["Job"],
            "batch/v1beta1": ["CronJob"],
            "networking.k8s.io/v1": ["Ingress", "NetworkPolicy"],
            "rbac.authorization.k8s.io/v1": ["Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"],
        }
    
    def is_builtin_resource(self, api_version: str, kind: str) -> bool:
        """Check if resource is a built-in Kubernetes resource"""
        return api_version in self.builtin_resources and kind in self.builtin_resources[api_version]
    
    def get_crd_from_cluster(self, api_version: str, kind: str, plural: Optional[str] = None) -> Optional[dict]:
        """Fetch CRD definition from local Kubernetes cluster"""
        try:
            import subprocess
            import json
            
            # Extract group and version
            if "/" in api_version:
                group, version = api_version.split("/", 1)
            else:
                group = ""
                version = api_version
            
            # Construct CRD name
            if plural:
                crd_name = f"{plural}.{group}" if group else plural
            else:
                # Attempt to pluralize the kind (basic pluralization)
                crd_name = f"{kind.lower()}s.{group}" if group else f"{kind.lower()}s"
            
            logger.info(f"Attempting to fetch CRD: {crd_name}")
            
            # Use kubectl to fetch CRD
            try:
                result = subprocess.run(
                    ["kubectl", "get", "crd", crd_name, "-o", "json"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    return json.loads(result.stdout)
                else:
                    logger.warning(f"kubectl failed to fetch CRD {crd_name}: {result.stderr}")
                    return None
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout fetching CRD {crd_name}")
                return None
            except FileNotFoundError:
                logger.warning("kubectl not found - Kubernetes CRD validation disabled")
                return None
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse CRD JSON for {crd_name}: {e}")
                return None
                
        except Exception as e:
            logger.warning(f"Failed to connect to Kubernetes cluster: {e}")
            return None
    
    def extract_schema_from_crd(self, crd: dict, version: str) -> Optional[dict]:
        """Extract OpenAPI schema from CRD for given version"""
        try:
            versions = crd.get("spec", {}).get("versions", [])
            
            for ver in versions:
                if ver.get("name") == version:
                    schema = ver.get("schema", {}).get("openAPIV3Schema")
                    if schema:
                        return schema
            
            logger.warning(f"Version {version} not found in CRD")
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract schema from CRD: {e}")
            return None
    
    def compile_validator(self, schema: dict, allow_partial: bool = False) -> Optional[Any]:
        """Compile a JSON schema validator from OpenAPI schema"""
        try:
            # Clean the schema to handle Kubernetes-specific formats
            cleaned_schema = self._clean_kubernetes_schema(schema)
            
            # For partial validation (overlays), remove required fields
            if allow_partial:
                cleaned_schema = self._make_schema_partial(cleaned_schema)
            
            # Focus on the spec portion of the schema
            if "properties" in cleaned_schema and "spec" in cleaned_schema["properties"]:
                spec_schema = cleaned_schema["properties"]["spec"]
                return fastjsonschema.compile(spec_schema)
            else:
                # Use the full schema if no spec property
                return fastjsonschema.compile(cleaned_schema)
        except Exception as e:
            logger.error(f"Failed to compile schema validator: {e}")
            return None
    
    def _make_schema_partial(self, schema: dict) -> dict:
        """Remove required field constraints and oneOf/anyOf constraints to allow partial validation"""
        import copy
        
        partial_schema = copy.deepcopy(schema)
        
        def remove_constraints(node):
            if isinstance(node, dict):
                # Remove 'required' array at any level
                if "required" in node:
                    del node["required"]
                
                # Remove oneOf/anyOf constraints at any level (these can fail when CEL expressions are removed)
                if "oneOf" in node:
                    del node["oneOf"]
                if "anyOf" in node:
                    del node["anyOf"]
                
                # Recursively process child nodes
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        remove_constraints(value)
            elif isinstance(node, list):
                for item in node:
                    if isinstance(item, (dict, list)):
                        remove_constraints(item)
        
        remove_constraints(partial_schema)
        return partial_schema
    
    def _clean_kubernetes_schema(self, schema: dict) -> dict:
        """Clean Kubernetes schema to be compatible with fastjsonschema and handle CEL expressions"""
        import copy
        
        cleaned = copy.deepcopy(schema)
        
        def clean_node(node):
            if isinstance(node, dict):
                # Remove/replace unsupported formats
                if "format" in node:
                    format_val = node["format"]
                    if format_val in ["int32", "int64"]:
                        # Remove format, keep type as integer
                        del node["format"]
                    elif format_val == "byte":
                        # Treat as string
                        node["type"] = "string"
                        del node["format"]
                    elif format_val == "date-time":
                        # Keep as string but remove format for fastjsonschema
                        node["type"] = "string"
                        del node["format"]
                
                # Note: CEL expression handling is done in validate_resource_spec method
                
                # Remove Kubernetes-specific extensions
                keys_to_remove = []
                for key in node.keys():
                    if key.startswith("x-kubernetes-"):
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del node[key]
                
                # Recursively clean child nodes (do this after modifying current node)
                for key, value in list(node.items()):
                    if isinstance(value, (dict, list)):
                        clean_node(value)
            elif isinstance(node, list):
                for item in node:
                    clean_node(item)
        
        clean_node(cleaned)
        return cleaned
    
    def _has_cel_expressions(self, obj) -> bool:
        """Check if an object contains any CEL expressions"""
        if isinstance(obj, str) and obj.startswith("="):
            return True
        elif isinstance(obj, dict):
            return any(self._has_cel_expressions(value) for value in obj.values())
        elif isinstance(obj, list):
            return any(self._has_cel_expressions(item) for item in obj)
        return False
    
    def _is_cel_related_error(self, error_msg: str, original_resource: dict) -> bool:
        """Check if a validation error is related to a field that contains CEL expressions"""
        # Extract field path from error message (e.g., "spec.ipCidrRange must be...")
        import re
        field_match = re.match(r"spec\.([^\s]+)", error_msg)
        if not field_match:
            return False
        
        field_path = field_match.group(1)
        
        # Navigate to the field in the original resource to check if it has CEL expressions
        try:
            if "spec" in original_resource:
                current = original_resource["spec"]
            else:
                current = original_resource
            
            # Handle nested field paths (e.g., "metadata.name")
            for part in field_path.split('.'):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return False
            
            # Check if this field contains CEL expressions
            return self._has_cel_expressions(current)
        except Exception:
            return False
    
    def _prepare_data_for_validation(self, data: dict, schema: dict) -> tuple[dict, bool]:
        """Prepare data for validation by removing CEL expressions (skip validation for dynamic values)
        
        Returns:
            tuple: (prepared_data, has_cel_expressions)
        """
        import copy
        
        prepared = copy.deepcopy(data)
        has_cel_expressions = False
        
        def remove_cel_expressions(obj):
            nonlocal has_cel_expressions
            if isinstance(obj, dict):
                # Collect keys with CEL expressions to remove after iteration
                keys_to_remove = []
                for key, value in obj.items():
                    if isinstance(value, str) and value.startswith("="):
                        # This is a CEL expression - remove it from validation entirely
                        keys_to_remove.append(key)
                        has_cel_expressions = True
                    else:
                        # Recursively process nested objects
                        remove_cel_expressions(value)
                
                # Remove CEL expression fields from validation
                for key in keys_to_remove:
                    del obj[key]
                    
            elif isinstance(obj, list):
                # Process list in reverse to safely remove items
                for i in range(len(obj) - 1, -1, -1):
                    item = obj[i]
                    if isinstance(item, str) and item.startswith("="):
                        # Remove CEL expression from array
                        obj.pop(i)
                        has_cel_expressions = True
                    else:
                        # Recursively process nested objects
                        remove_cel_expressions(item)
        
        remove_cel_expressions(prepared)
        return prepared, has_cel_expressions
    
    def _get_relaxed_validator(self, api_version: str, kind: str, plural: Optional[str], full_schema: dict, allow_partial: bool) -> Optional[Any]:
        """Get a validator with relaxed oneOf/anyOf validation for CEL expressions"""
        try:
            # Create a relaxed schema by removing oneOf/anyOf constraints
            relaxed_schema = self._relax_oneof_anyof_schema(full_schema)
            
            # Apply partial validation (remove required fields) if needed
            if not allow_partial:
                relaxed_schema = self._make_schema_partial(relaxed_schema)
            
            # Focus on the spec portion of the schema
            if "properties" in relaxed_schema and "spec" in relaxed_schema["properties"]:
                spec_schema = relaxed_schema["properties"]["spec"]
                return fastjsonschema.compile(spec_schema)
            else:
                # Use the full relaxed schema if no spec property
                return fastjsonschema.compile(relaxed_schema)
        except Exception as e:
            logger.debug(f"Failed to create relaxed validator: {e}")
            return None
    
    def _relax_oneof_anyof_schema(self, schema: dict) -> dict:
        """Remove oneOf/anyOf constraints from schema to allow partial validation with CEL expressions"""
        import copy
        
        relaxed = copy.deepcopy(schema)
        
        def relax_constraints(node):
            if isinstance(node, dict):
                # Remove oneOf and anyOf constraints
                if "oneOf" in node:
                    del node["oneOf"]
                if "anyOf" in node:
                    del node["anyOf"]
                
                # Recursively process child nodes
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        relax_constraints(value)
            elif isinstance(node, list):
                for item in node:
                    if isinstance(item, (dict, list)):
                        relax_constraints(item)
        
        relax_constraints(relaxed)
        return relaxed
    
    def get_validator(self, api_version: str, kind: str, plural: Optional[str] = None, allow_partial: bool = False) -> Optional[Any]:
        """Get compiled validator for given resource type"""
        cache_key = f"{api_version}/{kind}{'_partial' if allow_partial else ''}"
        
        if cache_key in self.compiled_validators:
            return self.compiled_validators[cache_key]
        
        # Skip validation for built-in Kubernetes resources
        if self.is_builtin_resource(api_version, kind):
            logger.info(f"Skipping CRD validation for built-in resource {api_version}/{kind}")
            return None
        
        # Extract version from apiVersion
        if "/" in api_version:
            version = api_version.split("/", 1)[1]
        else:
            version = api_version
        
        # Try to get CRD from cluster
        crd = self.get_crd_from_cluster(api_version, kind, plural)
        if not crd:
            return None
        
        # Extract schema
        schema = self.extract_schema_from_crd(crd, version)
        if not schema:
            return None
        
        # Compile validator (with partial support for overlays)
        validator = self.compile_validator(schema, allow_partial=allow_partial)
        if validator:
            self.compiled_validators[cache_key] = validator
        
        return validator
    
    def validate_resource_spec(self, resource_spec: dict, api_version: str, kind: str, 
                              plural: Optional[str] = None, allow_partial: bool = False) -> List[str]:
        """Validate a resource specification against its CRD schema"""
        cache_key = f"{api_version}/{kind}"
        
        # Skip validation for built-in Kubernetes resources
        if self.is_builtin_resource(api_version, kind):
            logger.info(f"Skipping CRD validation for built-in resource {api_version}/{kind}")
            return []
        
        # Get cached full schema or fetch it
        if cache_key not in self.full_schemas:
            # Extract version from apiVersion
            if "/" in api_version:
                version = api_version.split("/", 1)[1]
            else:
                version = api_version
            
            # Try to get CRD and schema
            crd = self.get_crd_from_cluster(api_version, kind, plural)
            if not crd:
                return []
            
            # Extract and cache schema
            full_schema = self.extract_schema_from_crd(crd, version)
            if not full_schema:
                return []
            
            self.full_schemas[cache_key] = full_schema
        else:
            full_schema = self.full_schemas[cache_key]
        
        # Get or compile validator (with partial support for overlays)
        validator = self.get_validator(api_version, kind, plural, allow_partial=allow_partial)
        if not validator:
            logger.debug(f"No validator available for {api_version}/{kind}")
            return []
        
        try:
            # Prepare data by removing CEL expression fields from validation
            if "spec" in resource_spec:
                spec_data = resource_spec["spec"]
                spec_schema = full_schema.get("properties", {}).get("spec", {})
            else:
                spec_data = resource_spec
                spec_schema = full_schema
            
            prepared_data, has_cel_expressions = self._prepare_data_for_validation(spec_data, spec_schema)
            
            # Validate the prepared data (CEL fields have been removed)
            validator(prepared_data)
            return []
        except fastjsonschema.JsonSchemaValueException as e:
            error_msg = str(e).replace("data.", "spec.").replace("data ", "spec ")
            
            # Check if this error is about a field that contains CEL expressions
            # If so, skip this error since CEL fields will be validated during FunctionTest execution
            if self._is_cel_related_error(error_msg, resource_spec):
                logger.debug(f"Skipping validation error for CEL field: {error_msg}")
                return []
            
            return [error_msg]
        except Exception as e:
            return [f"Validation error: {e}"]


class ResourceFunctionValidator:
    """Enhanced validator for ResourceFunction with Kubernetes CRD validation"""
    
    def __init__(self):
        self.k8s_validator = KubernetesCRDValidator()
    
    def validate_resource_function_spec(self, spec: dict) -> List[dict]:
        """Validate ResourceFunction spec with K8s CRD validation for resource fields"""
        errors = []
        
        # Get apiConfig for resource type information
        api_config = spec.get("apiConfig", {})
        api_version = api_config.get("apiVersion")
        kind = api_config.get("kind")
        plural = api_config.get("plural")  # Optional field
        
        if not api_version or not kind:
            # Can't do K8s validation without apiVersion and kind
            return errors
        
        # Determine if create is enabled (affects validation mode)
        create_config = spec.get("create", {})
        create_enabled = create_config.get("enabled", True)  # Default is True per CRD
        create_overlay = create_config.get("overlay")
        
        # Validate main resource specification
        # Use partial validation if:
        # 1. create is disabled (resource may be incomplete for patching), OR
        # 2. create overlay exists (overlay may complete the resource), OR
        # 3. resource contains CEL expressions (will be populated at runtime)
        resource_spec = spec.get("resource")
        if resource_spec:
            resource_has_cel = self._has_cel_expressions(resource_spec)
            allow_partial = not create_enabled or (create_enabled and create_overlay is not None) or resource_has_cel
            
            validation_errors = self.k8s_validator.validate_resource_spec(
                resource_spec, api_version, kind, plural, allow_partial=allow_partial
            )
            for error in validation_errors:
                if not create_enabled:
                    mode = "partial (create disabled)"
                elif create_overlay is not None:
                    mode = "partial (has create overlay)"
                elif resource_has_cel:
                    mode = "partial (has CEL expressions)"
                else:
                    mode = "full"
                errors.append({
                    "path": "spec.resource",
                    "message": f"Resource validation ({mode}): {error}",
                    "severity": "error"
                })
        
        # Validate overlays (partial validation - overlays are incomplete by design)
        overlays = spec.get("overlays", [])
        for i, overlay_item in enumerate(overlays):
            overlay_spec = overlay_item.get("overlay")
            if overlay_spec:
                validation_errors = self.k8s_validator.validate_resource_spec(
                    overlay_spec, api_version, kind, plural, allow_partial=True
                )
                for error in validation_errors:
                    errors.append({
                        "path": f"spec.overlays[{i}].overlay", 
                        "message": f"Overlay validation: {error}",
                        "severity": "error"
                    })
        
        # Validate create overlay by merging with base resource + all overlays (create overlays are applied at creation time)
        create_overlay = create_config.get("overlay")
        if create_overlay and resource_spec:
            # Start with base resource
            merged_resource = resource_spec.copy()
            
            # Apply all overlays in sequence
            overlays = spec.get("overlays", [])
            for overlay_item in overlays:
                overlay_spec = overlay_item.get("overlay")
                if overlay_spec:
                    merged_resource = self._merge_overlay_with_resource(merged_resource, overlay_spec)
            
            # Finally apply create overlay
            merged_resource = self._merge_overlay_with_resource(merged_resource, create_overlay)
            
            # Check if create overlay contains CEL expressions
            create_overlay_has_cel = self._has_cel_expressions(create_overlay)
            
            # Use partial validation if:
            # 1. create is disabled, OR
            # 2. create overlay contains CEL expressions (they'll be populated at runtime)
            use_partial = not create_enabled or create_overlay_has_cel
            
            validation_errors = self.k8s_validator.validate_resource_spec(
                merged_resource, api_version, kind, plural, allow_partial=use_partial
            )
            for error in validation_errors:
                if not create_enabled:
                    mode = "partial (create disabled)"
                elif create_overlay_has_cel:
                    mode = "partial (has CEL expressions)"
                else:
                    mode = "full"
                errors.append({
                    "path": "spec.create.overlay",
                    "message": f"Create overlay validation ({mode}, merged with resource + overlays): {error}",
                    "severity": "error"
                })
        
        return errors
    
    def _has_cel_expressions(self, obj) -> bool:
        """Check if an object contains any CEL expressions"""
        if isinstance(obj, str) and obj.startswith("="):
            return True
        elif isinstance(obj, dict):
            return any(self._has_cel_expressions(value) for value in obj.values())
        elif isinstance(obj, list):
            return any(self._has_cel_expressions(item) for item in obj)
        return False
    
    def _merge_overlay_with_resource(self, base_resource: dict, overlay: dict) -> dict:
        """Merge overlay with base resource (overlay values override base values)"""
        import copy
        
        merged = copy.deepcopy(base_resource)
        
        def deep_merge(base: dict, overlay_dict: dict):
            """Recursively merge overlay into base dictionary"""
            for key, value in overlay_dict.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    # Recursively merge nested dictionaries
                    deep_merge(base[key], value)
                else:
                    # Override value (including lists, primitives, or new keys)
                    base[key] = copy.deepcopy(value)
        
        deep_merge(merged, overlay)
        return merged


# Global validator instance
_k8s_validator = ResourceFunctionValidator()


def validate_resource_function_k8s(spec: dict) -> List[dict]:
    """Validate ResourceFunction spec with Kubernetes CRD validation"""
    return _k8s_validator.validate_resource_function_spec(spec)