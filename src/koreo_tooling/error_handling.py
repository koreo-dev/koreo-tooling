"""Unified error handling and diagnostic conversion for Koreo tooling"""

import re
from dataclasses import dataclass

from lsprotocol import types


@dataclass
class ValidationError:
    """Unified validation error with position information"""
    message: str
    path: str = ""
    line: int = 0
    character: int = 0
    end_line: int | None = None
    end_character: int | None = None
    severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error
    source: str = "koreo"
    
    def to_diagnostic(self) -> types.Diagnostic:
        """Convert to LSP Diagnostic with smart range calculation"""
        # Calculate end position based on error type
        if self.end_character is not None:
            # Use end_line if specified, otherwise same line
            end_line = self.end_line if self.end_line is not None else self.line
            end_pos = types.Position(line=end_line, character=self.end_character)
        else:
            # Smart end position calculation
            if 'must contain' in self.message or 'is required' in self.message:
                # For missing fields, highlight more of the line
                end_char = self.character + 40
            elif 'Unknown field' in self.message or 'additional property' in self.message:
                # For extra fields, try to highlight just the field name
                match = re.search(r"'([^']+)'", self.message)
                if match:
                    field_name = match.group(1)
                    end_char = self.character + len(field_name) + 2  # +2 for quotes
                else:
                    end_char = self.character + 20
            else:
                # Default highlighting
                field_length = len(self.path.split(".")[-1]) if self.path else 10
                end_char = self.character + field_length
            
            end_pos = types.Position(line=self.line, character=end_char)
        
        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=self.line, character=self.character),
                end=end_pos
            ),
            message=self.message,
            severity=self.severity,
            source=self.source
        )


class ErrorFormatter:
    """Utilities for formatting errors for different outputs"""
    
    @staticmethod
    def format_for_cli(errors: list[ValidationError]) -> str:
        """Format validation errors for CLI output"""
        if not errors:
            return "No validation errors found."
        
        formatted_lines = []
        for error in errors:
            location = f"line {error.line + 1}" if error.line > 0 else "unknown location"
            if error.path:
                location += f" ({error.path})"
            
            severity_symbol = "❌" if error.severity == types.DiagnosticSeverity.Error else "⚠️"
            formatted_lines.append(f"{severity_symbol} {location}: {error.message}")
        
        return "\n".join(formatted_lines)
    
    @staticmethod
    def format_for_lsp(errors: list[ValidationError]) -> list[types.Diagnostic]:
        """Convert validation errors to LSP diagnostics"""
        return [error.to_diagnostic() for error in errors]
    
    @staticmethod
    def format_cli_errors(errors: list[ValidationError], file_path) -> str:
        """Format validation errors for CLI output with file path"""
        if not errors:
            return f"\n{file_path}: No validation errors found."
        
        output = [f"\n{file_path}"]
        
        for error in errors:
            severity_label = {
                1: "ERROR",   # Error
                2: "WARNING", # Warning  
                3: "INFO",    # Information
                4: "HINT",    # Hint
            }.get(error.severity.value, "UNKNOWN")
            
            location = f"line {error.line + 1}" if error.line > 0 else "document"
            if error.path:
                location += f", {error.path}"
            
            output.append(f"  [{severity_label}] {error.message} ({location})")
        
        return "\n".join(output)
    
    @staticmethod
    def extract_path_from_error_message(error_message: str) -> str:
        """Extract field path from schema validation error message"""
        # Example: "spec.steps[0].label is required" -> "spec.steps[0].label"
        
        # Look for "spec.something" patterns
        match = re.search(r'spec\.[\w\[\]\.]+', error_message)
        if match:
            return match.group()
        
        # Look for field names in quotes
        match = re.search(r"'([^']+)'", error_message)
        if match:
            return f"spec.{match.group(1)}"
        
        return "spec"
    
    @staticmethod
    def extract_field_from_message(message: str) -> str | None:
        """Extract field name from error message"""
        
        # Pattern for "Unknown field 'fieldname'"
        match = re.search(r"Unknown field '([^']+)'", message)
        if match:
            return match.group(1)
        
        # Pattern for "additional property 'fieldname'"
        match = re.search(r"additional property '([^']+)'", message)
        if match:
            return match.group(1)
        
        # Pattern for field names in square brackets
        match = re.search(r"\['([^']+)'\]", message)
        if match:
            return match.group(1)
        
        return None


class ErrorCollector:
    """Utility for collecting and managing validation errors"""
    
    def __init__(self, source: str = "koreo"):
        self.errors: list[ValidationError] = []
        self.source = source
    
    def add_error(self, message: str, path: str = "", line: int = 0, 
                  character: int = 0, severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error):
        """Add a validation error"""
        self.errors.append(ValidationError(
            message=message,
            path=path,
            line=line,
            character=character,
            severity=severity,
            source=self.source
        ))
    
    def add_warning(self, message: str, path: str = "", line: int = 0, character: int = 0):
        """Add a validation warning"""
        self.add_error(message, path, line, character, types.DiagnosticSeverity.Warning)
    
    def extend(self, other_errors: list[ValidationError]):
        """Add multiple errors from another source"""
        self.errors.extend(other_errors)
    
    def has_errors(self) -> bool:
        """Check if any errors were collected"""
        return len(self.errors) > 0
    
    def has_error_level(self) -> bool:
        """Check if any error-level (not warning) issues were found"""
        return any(error.severity == types.DiagnosticSeverity.Error for error in self.errors)
    
    def get_errors(self) -> list[ValidationError]:
        """Get all collected errors"""
        return self.errors.copy()
    
    def clear(self):
        """Clear all collected errors"""
        self.errors.clear()


def create_yaml_parse_error(yaml_error: Exception, yaml_content: str = "") -> ValidationError:
    """Create a ValidationError from a YAML parsing exception"""
    if hasattr(yaml_error, 'problem_mark') and yaml_error.problem_mark:
        return ValidationError(
            message=f"YAML parsing error: {yaml_error}",
            line=yaml_error.problem_mark.line,
            character=yaml_error.problem_mark.column,
            severity=types.DiagnosticSeverity.Error,
            source="yaml-parser"
        )
    else:
        return ValidationError(
            message=f"YAML parsing error: {yaml_error}",
            line=0,
            character=0,
            severity=types.DiagnosticSeverity.Error,
            source="yaml-parser"
        )