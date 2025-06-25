from typing import Any


def is_cel_expression(value: Any) -> bool:
    """Check if a value is a CEL expression"""
    if not isinstance(value, str):
        return False
    return value.strip().startswith("=")


def has_cel_expressions(obj: Any) -> bool:
    """Recursively check if an object contains any CEL expressions"""
    if is_cel_expression(obj):
        return True
    if isinstance(obj, dict):
        return any(has_cel_expressions(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_cel_expressions(item) for item in obj)
    return False


def replace_cel_with_placeholders(data: dict, schema: dict) -> dict:
    """Replace CEL expressions with valid placeholder values"""
    result = {}
    properties = schema.get("properties", {})

    for key, value in data.items():
        if is_cel_expression(value):
            # Replace with appropriate placeholder based on schema type
            field_schema = properties.get(key, {})
            field_type = field_schema.get("type", "string")

            if field_type == "integer":
                result[key] = 1
            elif field_type == "number":
                result[key] = 1.0
            elif field_type == "boolean":
                result[key] = True
            elif field_type == "array":
                result[key] = []
            elif field_type == "object":
                result[key] = {}
            else:
                result[key] = "placeholder-string"
        elif isinstance(value, dict):
            field_schema = properties.get(key, {})
            if "properties" in field_schema:
                result[key] = replace_cel_with_placeholders(value, field_schema)
            else:
                result[key] = replace_cel_with_placeholders(value, {})
        elif isinstance(value, list):
            result[key] = []
            for item in value:
                if is_cel_expression(item):
                    result[key].append("placeholder-string")
                elif isinstance(item, dict):
                    result[key].append(replace_cel_with_placeholders(item, {}))
                else:
                    result[key].append(item)
        else:
            result[key] = value

    return result
