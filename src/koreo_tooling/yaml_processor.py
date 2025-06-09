"""Enhanced YAML processing using ruamel.yaml with native position tracking"""

import logging
from io import StringIO
from typing import Any, Iterator, NamedTuple

from ruyaml import YAML
from ruyaml.nodes import Node
from ruyaml.composer import ComposerError
from ruyaml.constructor import ConstructorError  
from ruyaml.parser import ParserError
from ruyaml.scanner import ScannerError
from lsprotocol import types

logger = logging.getLogger("koreo.tooling.yaml_processor")


class YamlPositionInfo(NamedTuple):
    """Position information for YAML elements"""
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None


class YamlProcessingError(NamedTuple):
    """YAML processing error with position information"""
    message: str
    position: YamlPositionInfo | None = None
    severity: types.DiagnosticSeverity = types.DiagnosticSeverity.Error


class EnhancedYamlProcessor:
    """YAML processor that leverages ruamel.yaml's native position tracking"""
    
    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.map_indent = 2
        self.yaml.sequence_indent = 4
        self.yaml.sequence_dash_offset = 2
        
    def load_documents(self, yaml_content: str) -> Iterator[tuple[Any, list[YamlProcessingError]]]:
        """Load YAML documents with native position tracking"""
        errors = []
        
        try:
            documents = list(self.yaml.load_all(yaml_content))
            for doc in documents:
                yield doc, []
                
        except (ScannerError, ParserError, ComposerError, ConstructorError) as e:
            error_pos = None
            if hasattr(e, 'problem_mark') and e.problem_mark:
                error_pos = YamlPositionInfo(
                    line=e.problem_mark.line,
                    column=e.problem_mark.column
                )
            
            errors.append(YamlProcessingError(
                message=str(e),
                position=error_pos,
                severity=types.DiagnosticSeverity.Error
            ))
            yield None, errors
    
    def get_position_info(self, obj: Any, key: str | int | None = None) -> YamlPositionInfo | None:
        """Get position information for an object or key using ruamel.yaml's metadata"""
        try:
            # For CommentedMap and CommentedSeq, ruamel.yaml stores position info
            if hasattr(obj, 'lc'):
                lc = obj.lc
                if key is not None and hasattr(lc, 'key') and key in lc.key:
                    # Position of a specific key
                    key_pos = lc.key(key)
                    return YamlPositionInfo(
                        line=key_pos[0],
                        column=key_pos[1]
                    )
                elif hasattr(lc, 'line') and hasattr(lc, 'col'):
                    # Position of the object itself
                    return YamlPositionInfo(
                        line=lc.line,
                        column=lc.col
                    )
            
            return None
            
        except Exception as e:
            logger.debug(f"Could not extract position info: {e}")
            return None
    
    def get_range_info(self, obj: Any) -> types.Range | None:
        """Get LSP Range for an object using ruamel.yaml's position data"""
        pos_info = self.get_position_info(obj)
        if not pos_info:
            return None
        
        # For now, create a single-point range
        # TODO: Extract end position from ruamel.yaml metadata
        start_pos = types.Position(line=pos_info.line, character=pos_info.column)
        end_pos = types.Position(line=pos_info.line, character=pos_info.column + 1)
        
        return types.Range(start=start_pos, end=end_pos)
    
    def dump_with_formatting(self, data: Any, preserve_formatting: bool = True) -> str:
        """Dump YAML while preserving formatting when possible"""
        stream = StringIO()
        self.yaml.dump(data, stream)
        return stream.getvalue()
    
    def validate_yaml_syntax(self, yaml_content: str) -> list[YamlProcessingError]:
        """Validate YAML syntax and return any errors"""
        errors = []
        
        try:
            # Just parse, don't load
            list(self.yaml.load_all(yaml_content))
        except (ScannerError, ParserError, ComposerError, ConstructorError) as e:
            error_pos = None
            if hasattr(e, 'problem_mark') and e.problem_mark:
                error_pos = YamlPositionInfo(
                    line=e.problem_mark.line,
                    column=e.problem_mark.column
                )
            
            errors.append(YamlProcessingError(
                message=f"YAML syntax error: {e}",
                position=error_pos,
                severity=types.DiagnosticSeverity.Error
            ))
        
        return errors


# Global processor instance
yaml_processor = EnhancedYamlProcessor()


def load_yaml_with_positions(yaml_content: str) -> Iterator[tuple[Any, list[YamlProcessingError]]]:
    """Convenience function to load YAML with position tracking"""
    return yaml_processor.load_documents(yaml_content)


def get_yaml_position(obj: Any, key: str | int | None = None) -> YamlPositionInfo | None:
    """Convenience function to get position info"""
    return yaml_processor.get_position_info(obj, key)


def validate_yaml(yaml_content: str) -> list[YamlProcessingError]:
    """Convenience function to validate YAML syntax"""
    return yaml_processor.validate_yaml_syntax(yaml_content)