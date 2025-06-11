"""CLI-specific validation utilities"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError as RuamelYAMLError

from .semantic import validate_with_semantics, ValidationError as SemanticValidationError, Severity as SemanticSeverity


class Severity(Enum):
    ERROR = 1
    WARNING = 2
    INFO = 3


@dataclass
class ValidationError:
    """Represents a validation error or warning"""
    message: str
    source: str
    line: Optional[int] = None
    column: Optional[int] = None
    severity: Severity = Severity.ERROR
    code: Optional[str] = None


def validate_koreo_yaml(content: str) -> list[ValidationError]:
    """Validate Koreo YAML using comprehensive semantic validation"""
    # Use semantic validation which includes structure checking and required fields
    semantic_errors = validate_with_semantics(content)
    
    # Convert semantic errors to CLI validation errors
    cli_errors = []
    for error in semantic_errors:
        severity = Severity.ERROR
        if error.severity == SemanticSeverity.WARNING:
            severity = Severity.WARNING
        elif error.severity == SemanticSeverity.INFO:
            severity = Severity.INFO
        
        cli_errors.append(ValidationError(
            message=error.message,
            source=error.source,
            line=error.line,
            column=error.column,
            severity=severity,
            code=error.code
        ))
    
    return cli_errors


def _validate_basic_yaml(content: str) -> list[ValidationError]:
    """Basic YAML validation"""
    errors = []
    
    try:
        yaml_parser = YAML()
        yaml_parser.preserve_quotes = True
        
        documents = list(yaml_parser.load_all(content))
        
        for doc_index, doc in enumerate(documents):
            if not isinstance(doc, dict):
                errors.append(ValidationError(
                    message=f"Document {doc_index + 1} is not a valid YAML object",
                    source="basic_validation",
                    severity=Severity.ERROR
                ))
                continue
            
            # Basic required field validation
            required_fields = ["apiVersion", "kind", "metadata"]
            for field in required_fields:
                if field not in doc:
                    line_num = None
                    if hasattr(doc, 'lc') and hasattr(doc.lc, 'line'):
                        line_num = doc.lc.line + 1
                    
                    errors.append(ValidationError(
                        message=f"Document {doc_index + 1} missing required field '{field}'",
                        source="validation",
                        line=line_num,
                        severity=Severity.ERROR
                    ))
            
            # Check metadata.name
            if "metadata" in doc:
                metadata = doc["metadata"]
                if not isinstance(metadata, dict) or "name" not in metadata:
                    line_num = None
                    if hasattr(metadata, 'lc') and hasattr(metadata.lc, 'line'):
                        line_num = metadata.lc.line + 1
                    elif hasattr(doc, 'lc') and hasattr(doc.lc, 'line'):
                        line_num = doc.lc.line + 1
                        
                    errors.append(ValidationError(
                        message=f"Document {doc_index + 1} missing required field 'metadata.name'",
                        source="basic_validation",
                        line=line_num,
                        severity=Severity.ERROR
                    ))
    
    except RuamelYAMLError as e:
        # Handle YAML parsing errors
        error_msg = str(e)
        line = getattr(e, 'problem_mark', None)
        line_num = line.line + 1 if line else None
        column_num = line.column if line else None
        
        errors.append(ValidationError(
            message=f"YAML syntax error: {error_msg}",
            source="basic_validation",
            line=line_num,
            column=column_num,
            severity=Severity.ERROR
        ))
    except Exception as e:
        errors.append(ValidationError(
            message=f"Unexpected error during validation: {str(e)}",
            source="basic_validation",
            severity=Severity.ERROR
        ))
    
    return errors


def format_validation_errors(file_path: Path, errors: list[ValidationError]) -> str:
    """Format validation errors for CLI output"""
    if not errors:
        return ""
    
    lines = [f"\n{file_path}:"]
    
    for error in errors:
        location = ""
        if error.line is not None:
            location = f"{error.line}"
            if error.column is not None:
                location += f":{error.column}"
            location += " "
        
        severity = error.severity.name.lower()
        code = f" [{error.code}]" if error.code else ""
        
        lines.append(f"  {location}{severity}: {error.message}{code}")
    
    return "\n".join(lines)