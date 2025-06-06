"""Schema validation module for Koreo resources with enhanced diagnostics"""

import logging

import yaml
from koreo import schema
from koreo.function_test.structure import FunctionTest
from koreo.resource_function.structure import ResourceFunction
from koreo.resource_template.structure import ResourceTemplate
from koreo.result import PermFail
from koreo.value_function.structure import ValueFunction
from koreo.workflow.structure import Workflow
from lsprotocol import types

from koreo_tooling.k8s_validation import validate_resource_function_k8s

logger = logging.getLogger("koreo.tooling.schema_validation")

# Map API kinds to their corresponding structure classes
KIND_TO_CLASS = {
    "ValueFunction": ValueFunction,
    "ResourceFunction": ResourceFunction,
    "ResourceTemplate": ResourceTemplate,
    "Workflow": Workflow,
    "FunctionTest": FunctionTest,
}


class ValidationError:
    """Enhanced validation error with position information"""
    
    def __init__(
        self,
        message: str,
        path: str = "",
        line: int = 0,
        character: int = 0,
        severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error
    ):
        self.message = message
        self.path = path
        self.line = line
        self.character = character
        self.severity = severity
    
    def to_diagnostic(self) -> types.Diagnostic:
        """Convert to LSP Diagnostic"""
        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=self.line, character=self.character),
                end=types.Position(line=self.line, character=self.character + len(self.path.split(".")[-1]) if self.path else 10)
            ),
            message=self.message,
            severity=self.severity,
            source="koreo-schema"
        )


class SchemaValidator:
    """Enhanced schema validator with detailed error reporting"""
    
    def __init__(self):
        self.validators_loaded = False
    
    def ensure_validators_loaded(self):
        """Ensure schema validators are loaded"""
        if not self.validators_loaded:
            from koreo_tooling import load_schema_validators
            load_schema_validators()
            self.validators_loaded = True
    
    def validate_yaml_content(self, yaml_content: str) -> list[ValidationError]:
        """Validate YAML content and return detailed errors"""
        errors = []
        
        try:
            # Parse YAML
            docs = list(yaml.safe_load_all(yaml_content))
        except yaml.YAMLError as e:
            error_line = getattr(e, 'problem_mark', None)
            line_num = error_line.line if error_line else 0
            char_num = error_line.column if error_line else 0
            
            errors.append(ValidationError(
                message=f"YAML parsing error: {e}",
                line=line_num,
                character=char_num,
                severity=types.DiagnosticSeverity.Error
            ))
            return errors
        
        # Validate each document
        for doc_idx, doc in enumerate(docs):
            if not doc:
                continue
            
            doc_errors = self.validate_document(doc, doc_idx)
            errors.extend(doc_errors)
        
        return errors
    
    def validate_document(self, document: dict, doc_index: int = 0) -> list[ValidationError]:
        """Validate a single Koreo document"""
        errors = []
        
        # Basic structure validation
        if not isinstance(document, dict):
            errors.append(ValidationError(
                message="Document must be a YAML object",
                line=doc_index,
                severity=types.DiagnosticSeverity.Error
            ))
            return errors
        
        # Check required fields
        required_fields = ["apiVersion", "kind", "metadata", "spec"]
        for field in required_fields:
            if field not in document:
                errors.append(ValidationError(
                    message=f"Missing required field: {field}",
                    path=field,
                    line=doc_index,
                    severity=types.DiagnosticSeverity.Error
                ))
        
        # Validate API version
        api_version = document.get("apiVersion")
        if api_version and not api_version.startswith("koreo.dev/"):
            errors.append(ValidationError(
                message=f"Invalid apiVersion: {api_version}. Expected 'koreo.dev/v1beta1'",
                path="apiVersion",
                line=doc_index,
                severity=types.DiagnosticSeverity.Warning
            ))
        
        # Get resource kind and validate
        kind = document.get("kind")
        if not kind:
            return errors
        
        if kind not in KIND_TO_CLASS:
            errors.append(ValidationError(
                message=f"Unknown resource kind: {kind}. Supported kinds: {', '.join(KIND_TO_CLASS.keys())}",
                path="kind",
                line=doc_index,
                severity=types.DiagnosticSeverity.Error
            ))
            return errors
        
        # Validate metadata
        metadata_errors = self.validate_metadata(document.get("metadata", {}))
        errors.extend(metadata_errors)
        
        # Validate spec using koreo-core schema validation
        spec_errors = self.validate_spec(document.get("spec", {}), kind, api_version)
        errors.extend(spec_errors)
        
        # Add Kubernetes CRD validation for ResourceFunction
        if kind == "ResourceFunction":
            k8s_errors = self.validate_resource_function_k8s(document.get("spec", {}))
            errors.extend(k8s_errors)
        
        return errors
    
    def validate_metadata(self, metadata: dict) -> list[ValidationError]:
        """Validate metadata section"""
        errors = []
        
        if not isinstance(metadata, dict):
            errors.append(ValidationError(
                message="metadata must be an object",
                path="metadata",
                severity=types.DiagnosticSeverity.Error
            ))
            return errors
        
        # Validate name
        name = metadata.get("name")
        if not name:
            errors.append(ValidationError(
                message="metadata.name is required",
                path="metadata.name",
                severity=types.DiagnosticSeverity.Error
            ))
        elif not isinstance(name, str):
            errors.append(ValidationError(
                message="metadata.name must be a string",
                path="metadata.name",
                severity=types.DiagnosticSeverity.Error
            ))
        elif not name.replace("-", "").replace("_", "").isalnum():
            errors.append(ValidationError(
                message="metadata.name must contain only alphanumeric characters, hyphens, and underscores",
                path="metadata.name",
                severity=types.DiagnosticSeverity.Warning
            ))
        
        return errors
    
    def validate_spec(self, spec: dict, kind: str, api_version: str | None = None) -> list[ValidationError]:
        """Validate spec using koreo-core schema validation"""
        errors = []
        self.ensure_validators_loaded()
        
        try:
            resource_class = KIND_TO_CLASS[kind]
            # Extract just the version part from api_version (e.g., "v1beta1" from "koreo.dev/v1beta1")
            version = None
            if api_version:
                parts = api_version.split("/")
                version = parts[-1] if parts else None
            
            validation_result = schema.validate(
                resource_type=resource_class,
                spec=spec,
                schema_version=version,
                validation_required=True
            )
            
            if isinstance(validation_result, PermFail):
                # Parse the validation error to extract useful information
                error_msg = validation_result.message
                
                # Try to extract field path from error message
                path = self._extract_path_from_error(error_msg)
                
                errors.append(ValidationError(
                    message=error_msg,
                    path=path,
                    severity=types.DiagnosticSeverity.Error
                ))
        
        except Exception as e:
            logger.exception(f"Error validating {kind} spec")
            errors.append(ValidationError(
                message=f"Schema validation failed: {e}",
                path="spec",
                severity=types.DiagnosticSeverity.Error
            ))
        
        return errors
    
    def _extract_path_from_error(self, error_message: str) -> str:
        """Extract field path from schema validation error message"""
        # Example: "spec.steps[0].label is required" -> "spec.steps[0].label"
        # This is a simple heuristic and could be improved
        import re
        
        # Look for "spec.something" patterns
        match = re.search(r'spec\.[\w\[\]\.]+', error_message)
        if match:
            return match.group()
        
        # Look for field names in quotes
        match = re.search(r"'([^']+)'", error_message)
        if match:
            return f"spec.{match.group(1)}"
        
        return "spec"
    
    def validate_resource_function_k8s(self, spec: dict) -> list[ValidationError]:
        """Validate ResourceFunction with Kubernetes CRD validation"""
        errors = []
        
        try:
            k8s_validation_errors = validate_resource_function_k8s(spec)
            
            for error_info in k8s_validation_errors:
                errors.append(ValidationError(
                    message=error_info["message"],
                    path=error_info["path"],
                    severity=types.DiagnosticSeverity.Error if error_info["severity"] == "error" else types.DiagnosticSeverity.Warning
                ))
        except Exception as e:
            logger.exception("Error during K8s CRD validation")
            errors.append(ValidationError(
                message=f"K8s validation failed: {e}",
                path="spec",
                severity=types.DiagnosticSeverity.Warning
            ))
        
        return errors


# Global validator instance
_validator = SchemaValidator()


def validate_koreo_yaml(yaml_content: str) -> list[ValidationError]:
    """Validate Koreo YAML content and return validation errors"""
    return _validator.validate_yaml_content(yaml_content)


def validate_koreo_document(document: dict) -> list[ValidationError]:
    """Validate a single Koreo document"""
    return _validator.validate_document(document)


def get_diagnostics_for_file(yaml_content: str) -> list[types.Diagnostic]:
    """Get LSP diagnostics for a YAML file"""
    errors = validate_koreo_yaml(yaml_content)
    return [error.to_diagnostic() for error in errors]