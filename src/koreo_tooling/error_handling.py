"""Simple error handling for validation diagnostics"""

from dataclasses import dataclass

from lsprotocol import types


@dataclass
class ValidationError:
    """Simple validation error with position information"""

    message: str
    path: str = ""
    line: int = 0
    character: int = 0
    severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error
    source: str = "koreo"

    def to_diagnostic(
        self, range_override: types.Range = None
    ) -> types.Diagnostic:
        """Convert to LSP Diagnostic"""
        if range_override:
            diagnostic_range = range_override
        else:
            # Simple range - highlight a reasonable portion
            end_char = self.character + 20
            diagnostic_range = types.Range(
                start=types.Position(line=self.line, character=self.character),
                end=types.Position(line=self.line, character=end_char),
            )

        return types.Diagnostic(
            range=diagnostic_range,
            message=self.message,
            severity=self.severity,
            source=self.source,
        )
