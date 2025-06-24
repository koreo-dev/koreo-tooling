"""Koreo tooling package initialization"""

import logging

# Module-level logger
logger = logging.getLogger("koreo.tooling")

# Expose key utilities at package level
from .cel_utils import CelExpressionDetector, CelPlaceholderGenerator
from .error_handling import ValidationError
from .k8s_validation import (
    get_crd_schema,
    is_k8s_validation_enabled,
    set_k8s_validation_enabled,
    validate_spec,
    validate_resource_function,
    validate_resource_function_k8s,
    is_cel_expression,
    has_cel_expressions,
    replace_cel_with_placeholders,
    clean_schema,
    make_partial_schema,
    merge_overlays,
    is_cel_related_error,
)

__all__ = [
    # CEL utilities
    "CelExpressionDetector",
    "CelPlaceholderGenerator",
    # Error handling
    "ValidationError",
    # K8s validation
    "get_crd_schema",
    "set_k8s_validation_enabled",
    "is_k8s_validation_enabled",
    "validate_spec",
    "validate_resource_function",
    "validate_resource_function_k8s",
    "is_cel_expression",
    "has_cel_expressions",
    "replace_cel_with_placeholders",
    "clean_schema",
    "make_partial_schema",
    "merge_overlays",
    "is_cel_related_error",
]
