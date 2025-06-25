"""Koreo tooling package initialization"""

import logging

from .cel_utils import (
    has_cel_expressions,
    is_cel_expression,
    replace_cel_with_placeholders,
)
from .error_handling import ValidationError
from .k8s_validation import (
    clean_schema,
    get_crd_schema,
    is_k8s_validation_enabled,
    make_partial_schema,
    merge_overlays,
    set_k8s_validation_enabled,
    validate_resource_function,
    validate_resource_function_k8s,
    validate_spec,
)

# Module-level logger
logger = logging.getLogger("koreo.tooling")

__all__ = [
    # CEL utilities
    "has_cel_expressions",
    "is_cel_expression",
    "replace_cel_with_placeholders",
    # Error handling
    "ValidationError",
    # K8s validation
    "clean_schema",
    "get_crd_schema",
    "is_k8s_validation_enabled",
    "make_partial_schema",
    "merge_overlays",
    "set_k8s_validation_enabled",
    "validate_resource_function",
    "validate_resource_function_k8s",
    "validate_spec",
]
