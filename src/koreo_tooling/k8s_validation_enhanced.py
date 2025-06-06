"""Enhanced K8s validation with line number mapping for better diagnostics"""

import logging

from lsprotocol import types

try:
    from .error_handling import ErrorFormatter, ValidationError
    from .k8s_validation import validate_resource_function
    from .yaml_utils import YamlPositionTracker, YamlProcessor
except ImportError:
    from koreo_tooling.error_handling import ErrorFormatter, ValidationError
    from koreo_tooling.k8s_validation import validate_resource_function
    from koreo_tooling.yaml_utils import YamlPositionTracker, YamlProcessor

logger = logging.getLogger("koreo.tooling.k8s_validation_enhanced")


class PositionedError(ValidationError):
    """Enhanced validation error with position information - extends ValidationError"""
    
    def __init__(self, message: str, path: str, line: int, column: int,
                 end_line: int | None = None, end_column: int | None = None,
                 severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error):
        super().__init__(
            message=message,
            path=path,
            line=line,
            character=column,
            end_line=end_line,
            end_character=end_column,
            severity=severity,
            source="koreo-k8s"
        )
        # Backward compatibility properties
        self.column = column
        self.end_column = end_column


# Use shared YamlPositionTracker from yaml_utils


def map_error_to_position(error: dict, position_tracker: YamlPositionTracker, 
                         yaml_lines: list[str]) -> PositionedError:
    """Map validation error to specific line position"""
    path = error.get('path', '')
    message = error.get('message', '')
    
    # Try to use position tracker first
    position = position_tracker.get_position(path)
    if position:
        return PositionedError(
            message=message,
            path=path,
            line=position['line'],
            column=position['column'],
            end_line=position.get('end_line'),
            end_column=position.get('end_column'),
            severity=types.DiagnosticSeverity.Error
        )
    
    # Fallback to simple line search for specific paths
    fallback_line = YamlProcessor.find_line_for_path(yaml_lines, path)
    if fallback_line is not None:
        import re
        # Find the column position of "spec"
        spec_match = re.search(r'(\s*)spec:', yaml_lines[fallback_line])
        column = len(spec_match.group(1)) if spec_match else 0
        
        return PositionedError(
            message=message,
            path=path,
            line=fallback_line,
            column=column,
            end_line=fallback_line,
            end_column=column + 4,  # Length of "spec"
            severity=types.DiagnosticSeverity.Error
        )
    
    # For other errors or fallback, just use line 0
    return PositionedError(
        message=message,
        path=path,
        line=0,
        column=0,
        severity=types.DiagnosticSeverity.Error
    )


# Use shared field extraction from error_handling
_extract_field_from_message = ErrorFormatter.extract_field_from_message


def validate_resource_function_with_positions(yaml_content: str) -> list[PositionedError]:
    """Validate ResourceFunction and return errors with line positions"""
    errors = []
    
    try:
        # Parse YAML documents using shared utilities
        docs, yaml_errors = YamlProcessor.safe_load_all(yaml_content)
        yaml_lines = yaml_content.split('\n')
        
        # Handle YAML parsing errors
        for yaml_error in yaml_errors:
            position = YamlProcessor.get_yaml_parse_error_position(yaml_error)
            if position:
                errors.append(PositionedError(
                    message=f"YAML parsing error: {yaml_error}",
                    path='',
                    line=position.line,
                    column=position.character,
                    severity=types.DiagnosticSeverity.Error
                ))
        
        # Create position tracker
        tracker = YamlPositionTracker(yaml_content)
        
        # Find ResourceFunction documents
        for doc in docs:
            if doc and doc.get('kind') == 'ResourceFunction':
                spec = doc.get('spec', {})
                
                # Run validation
                validation_errors = validate_resource_function(spec)
                
                # Map errors to positions
                for error in validation_errors:
                    error_dict = {
                        'path': error.path,
                        'message': error.message,
                        'severity': getattr(error, 'severity', 'error')
                    }
                    positioned_error = map_error_to_position(error_dict, tracker, yaml_lines)
                    errors.append(positioned_error)
    
    except Exception as e:
        # Catch-all for unexpected errors
        errors.append(PositionedError(
            message=f"Validation error: {e}",
            path='',
            line=0,
            column=0,
            severity=types.DiagnosticSeverity.Error
        ))
    
    return errors


def get_enhanced_diagnostics(yaml_content: str) -> list[types.Diagnostic]:
    """Get VS Code diagnostics with proper line positions"""
    errors = validate_resource_function_with_positions(yaml_content)
    diagnostics = []
    
    for error in errors:
        # Create range for the error
        start = types.Position(line=error.line, character=error.column)
        
        # For end position, use provided end or estimate based on error type
        if error.end_line is not None and error.end_column is not None:
            end = types.Position(line=error.end_line, character=error.end_column)
        else:
            # Use the end position from the error
            end = types.Position(line=error.end_line or error.line, 
                               character=error.end_column or (error.column + 20))
        
        diagnostics.append(types.Diagnostic(
            range=types.Range(start=start, end=end),
            message=error.message,
            severity=error.severity,
            source="koreo-k8s"
        ))
    
    return diagnostics