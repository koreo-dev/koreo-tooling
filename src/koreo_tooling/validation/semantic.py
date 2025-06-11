"""Semantic validation using the existing koreo_tooling indexing system"""

from typing import Any, Generator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from koreo_tooling.indexing import IndexingLoader, STRUCTURE_KEY
from koreo_tooling.indexing.semantics import (
    SemanticAnchor,
    Severity as SemanticSeverity,
    extract_diagnostics,
    flatten,
)


class Severity(Enum):
    ERROR = 1
    WARNING = 2
    INFO = 3


@dataclass
class ValidationError:
    """Represents a validation error or warning"""
    message: str
    source: str
    line: int | None = None
    column: int | None = None
    severity: Severity = Severity.ERROR
    code: str | None = None


class MockTextDocument:
    """Mock TextDocument for the IndexingLoader"""
    def __init__(self, content: str):
        self.source = content
        self.lines = content.splitlines()


def validate_with_semantics(content: str) -> list[ValidationError]:
    """Validate using the existing semantic validation system"""
    errors = []
    
    try:
        import yaml
        mock_doc = MockTextDocument(content)
        
        # Use the existing IndexingLoader
        def custom_loader(stream):
            return IndexingLoader(stream, doc=mock_doc)
        
        documents = list(yaml.load_all(content, Loader=custom_loader))
        
        for doc_data in documents:
            if isinstance(doc_data, tuple):
                # Extract the document from the (hash, doc) tuple
                _, doc = doc_data
            else:
                doc = doc_data
                
            if doc and STRUCTURE_KEY in doc:
                structure = doc[STRUCTURE_KEY]
                if isinstance(structure, SemanticAnchor):
                    # Flatten the semantic structure to get all nodes
                    flattened = flatten(structure)
                    
                    # Extract diagnostics from the flattened nodes
                    diagnostic_nodes = extract_diagnostics(flattened)
                    
                    # Convert diagnostics to ValidationError objects
                    for node in diagnostic_nodes:
                        if node.diagnostic:
                            severity = Severity.ERROR
                            if node.diagnostic.severity == SemanticSeverity.warning:
                                severity = Severity.WARNING
                            elif node.diagnostic.severity == SemanticSeverity.info:
                                severity = Severity.INFO
                            
                            errors.append(ValidationError(
                                message=node.diagnostic.message,
                                source="semantic_validation",
                                line=node.position.line + 1,  # Convert to 1-based
                                column=node.position.character,
                                severity=severity
                            ))
                    
                    # Add custom required field validation for Koreo resources
                    if isinstance(doc, dict):
                        errors.extend(_validate_required_koreo_fields(doc))
    
    except yaml.YAMLError as e:
        # Handle YAML parsing errors
        error_msg = str(e)
        line = None
        column = None
        
        if hasattr(e, 'problem_mark'):
            line = e.problem_mark.line + 1
            column = e.problem_mark.column
        
        errors.append(ValidationError(
            message=f"YAML syntax error: {error_msg}",
            source="semantic_validation",
            line=line,
            column=column,
            severity=Severity.ERROR
        ))
    except Exception as e:
        errors.append(ValidationError(
            message=f"Unexpected error during semantic validation: {str(e)}",
            source="semantic_validation",
            severity=Severity.ERROR
        ))
    
    return errors


def _validate_required_koreo_fields(doc: dict) -> list[ValidationError]:
    """Validate required fields for Koreo resource types"""
    errors = []
    
    if not isinstance(doc, dict):
        return errors
    
    api_version = doc.get("apiVersion", "")
    kind = doc.get("kind", "")
    
    # Only validate Koreo resources
    if not api_version.startswith("koreo.dev/"):
        return errors
    
    # Define required fields for each Koreo resource type
    required_fields = {
        "ResourceFunction": {
            "spec": "ResourceFunction requires a 'spec' field",
            "spec.apiConfig": "ResourceFunction requires 'spec.apiConfig' field",
        },
        "ValueFunction": {
            "spec": "ValueFunction requires a 'spec' field",
        },
        "Workflow": {
            "spec": "Workflow requires a 'spec' field",
            "spec.steps": "Workflow requires 'spec.steps' field",
        },
        "FunctionTest": {
            "spec": "FunctionTest requires a 'spec' field",
            "spec.functionRef": "FunctionTest requires 'spec.functionRef' field",
        },
        "ResourceTemplate": {
            "spec": "ResourceTemplate requires a 'spec' field",
            "spec.template": "ResourceTemplate requires 'spec.template' field",
        }
    }
    
    if kind not in required_fields:
        return errors
    
    # Check each required field
    for field_path, error_message in required_fields[kind].items():
        if not _check_field_exists(doc, field_path):
            errors.append(ValidationError(
                message=error_message,
                source="semantic_validation",
                severity=Severity.ERROR
            ))
    
    return errors


def _check_field_exists(doc: dict, field_path: str) -> bool:
    """Check if a nested field exists in a document (e.g., 'spec.apiConfig')"""
    parts = field_path.split('.')
    current = doc
    
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    
    return True
