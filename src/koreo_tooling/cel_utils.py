"""Utilities for CEL (Common Expression Language) detection and handling"""

from typing import Any


class CelExpressionDetector:
    """Utilities for detecting and working with CEL expressions"""
    
    @staticmethod
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
    
    @staticmethod
    def has_cel_expressions(obj: Any) -> bool:
        """Recursively check if an object contains any CEL expressions"""
        if CelExpressionDetector.is_cel_expression(obj):
            return True
        if isinstance(obj, dict):
            return any(CelExpressionDetector.has_cel_expressions(v) for v in obj.values())
        if isinstance(obj, list):
            return any(CelExpressionDetector.has_cel_expressions(item) for item in obj)
        return False
    
    @staticmethod
    def extract_cel_expressions(obj: dict, path_prefix: str = "") -> list[tuple[str, str]]:
        """Extract all CEL expressions from an object with their paths"""
        expressions = []
        
        def _extract_recursive(current_obj: Any, current_path: str):
            if CelExpressionDetector.is_cel_expression(current_obj):
                expressions.append((current_path, current_obj))
            elif isinstance(current_obj, dict):
                for key, value in current_obj.items():
                    new_path = f"{current_path}.{key}" if current_path else key
                    _extract_recursive(value, new_path)
            elif isinstance(current_obj, list):
                for i, item in enumerate(current_obj):
                    new_path = f"{current_path}[{i}]" if current_path else f"[{i}]"
                    _extract_recursive(item, new_path)
        
        _extract_recursive(obj, path_prefix)
        return expressions
    
    @staticmethod
    def is_cel_related_error(error_msg: str, original_data: dict) -> bool:
        """Check if validation error is about a field that contains CEL expressions"""
        import re
        
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
        
        return CelExpressionDetector.is_cel_expression(current)


class CelPlaceholderGenerator:
    """Generates appropriate placeholder values for CEL expressions based on expected types"""
    
    @staticmethod
    def get_placeholder_for_type(field_schema: dict, field_name: str = "") -> Any:
        """Get appropriate placeholder value based on schema type and field name"""
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
                placeholder_item = CelPlaceholderGenerator.get_placeholder_for_type(items_schema)
                return [placeholder_item] if placeholder_item is not None else []
            return []
        elif field_type == "object":
            return {}
        else:
            # Fallback to field name heuristics for common Kubernetes fields
            return CelPlaceholderGenerator._get_kubernetes_field_placeholder(field_name)
    
    @staticmethod
    def _get_kubernetes_field_placeholder(field_name: str) -> Any:
        """Get placeholder for common Kubernetes field names when schema type is missing"""
        if field_name == "env":
            # Kubernetes env is always an array of objects
            return [{"name": "PLACEHOLDER", "value": "placeholder"}]
        elif field_name in ["ports", "containers", "volumes", "volumeMounts"]:
            # These are typically arrays
            return []
        elif field_name in ["labels", "annotations", "selector"]:
            # These are typically objects
            return {}
        else:
            return "placeholder-string"
    
    @staticmethod
    def replace_cel_with_placeholders(data: dict, schema: dict) -> dict:
        """Replace CEL expressions with valid placeholder values based on schema types"""
        result = {}
        
        # Get properties from schema
        properties = schema.get("properties", {})
        
        for key, value in data.items():
            if CelExpressionDetector.is_cel_expression(value):
                # Replace CEL expression with placeholder based on expected type
                field_schema = properties.get(key, {})
                
                # Special handling for common Kubernetes field names when schema type is missing
                if not field_schema.get("type"):
                    result[key] = CelPlaceholderGenerator._get_kubernetes_field_placeholder(key)
                else:
                    result[key] = CelPlaceholderGenerator.get_placeholder_for_type(field_schema, key)
            elif isinstance(value, dict):
                # Recursively process nested objects
                field_schema = properties.get(key, {})
                if "properties" in field_schema:
                    result[key] = CelPlaceholderGenerator.replace_cel_with_placeholders(value, field_schema)
                else:
                    result[key] = CelPlaceholderGenerator.replace_cel_with_placeholders(value, {})
            elif isinstance(value, list):
                # Process lists
                cleaned_list = []
                list_schema = properties.get(key, {})
                items_schema = list_schema.get("items", {})
                
                for item in value:
                    if CelExpressionDetector.is_cel_expression(item):
                        # Use appropriate placeholder for list items
                        if items_schema:
                            placeholder = CelPlaceholderGenerator.get_placeholder_for_type(items_schema)
                            cleaned_list.append(placeholder)
                        else:
                            cleaned_list.append("placeholder-string")
                    elif isinstance(item, dict):
                        if items_schema and "properties" in items_schema:
                            cleaned_list.append(CelPlaceholderGenerator.replace_cel_with_placeholders(item, items_schema))
                        else:
                            cleaned_list.append(CelPlaceholderGenerator.replace_cel_with_placeholders(item, {}))
                    else:
                        cleaned_list.append(item)
                result[key] = cleaned_list
            else:
                result[key] = value
        
        return result