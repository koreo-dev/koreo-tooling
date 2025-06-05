"""CEL expression diagnostics for common issues"""

import re
from typing import List, Optional, Tuple

from lsprotocol import types
from koreo_tooling.indexing.semantics import SemanticNode, Position


# Common CEL expression patterns that might be problematic
CEL_DIAGNOSTIC_PATTERNS = [
    {
        "pattern": r"=\s*['\"].*['\"]",
        "message": "CEL expressions should not start with quoted strings. Did you mean to use a literal value without '='?",
        "severity": types.DiagnosticSeverity.Warning,
    },
    {
        "pattern": r"=\s*\$\s*\{",
        "message": "Use ${} for step references outside CEL expressions, not inside them",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*\s+and\s+",
        "message": "Use '&&' instead of 'and' in CEL expressions",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*\s+or\s+",
        "message": "Use '||' instead of 'or' in CEL expressions",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*\s+not\s+",
        "message": "Use '!' instead of 'not' in CEL expressions",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*[\[\]]\s*\d+\s*[\[\]]",  
        "message": "Array access should use brackets directly: array[0], not array [0]",
        "severity": types.DiagnosticSeverity.Warning,
    },
    {
        "pattern": r"=\s*if\s+",
        "message": "Use ternary operator (condition ? true_value : false_value) instead of 'if' in CEL",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*[^!<>=]=(?!=)",
        "message": "Single '=' is assignment, use '==' for equality comparison",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=\s*\.",
        "message": "CEL expression should not start with a dot. Did you mean 'inputs.' or 'self.'?",
        "severity": types.DiagnosticSeverity.Error,
    },
    {
        "pattern": r"=.*null\s*\|\|\s*",
        "message": "For null coalescing, consider using has() to check field existence",
        "severity": types.DiagnosticSeverity.Information,
    },
]


def check_balanced_brackets(expression: str) -> List[Tuple[int, str]]:
    """Check for unbalanced brackets, parentheses, and braces"""
    issues = []
    stack = []
    pairs = {'(': ')', '[': ']', '{': '}'}
    closing = {')': '(', ']': '[', '}': '{'}
    
    for i, char in enumerate(expression):
        if char in pairs:
            stack.append((char, i))
        elif char in closing:
            if not stack or stack[-1][0] != closing[char]:
                issues.append((i, f"Unmatched closing '{char}'"))
            else:
                stack.pop()
    
    for char, pos in stack:
        issues.append((pos, f"Unmatched opening '{char}'"))
    
    return issues


def check_string_interpolation(expression: str) -> List[Tuple[int, str]]:
    """Check for common string interpolation mistakes"""
    issues = []
    
    # Check for Python-style f-string syntax
    if re.search(r'["\'].*\{[^}]+\}.*["\']', expression):
        match = re.search(r'["\'].*(\{[^}]+\}).*["\']', expression)
        if match:
            issues.append((
                match.start(1),
                "String interpolation not supported in CEL. Use string concatenation with +"
            ))
    
    # Check for template literal syntax
    if '`' in expression:
        pos = expression.find('`')
        issues.append((pos, "Template literals not supported. Use single or double quotes"))
    
    return issues


def check_function_calls(expression: str) -> List[Tuple[int, str]]:
    """Check for common function call mistakes"""
    issues = []
    
    # Check for functions without parentheses
    func_pattern = r'\b(size|has|all|exists|exists_one|map|filter|matches|contains|startsWith|endsWith)\b(?!\s*\()'
    for match in re.finditer(func_pattern, expression):
        issues.append((
            match.start(),
            f"Function '{match.group(1)}' requires parentheses"
        ))
    
    # Check for incorrect map/filter syntax
    map_filter = r'\b(map|filter)\s*\(\s*([^,)]+)\s*\)'
    for match in re.finditer(map_filter, expression):
        if ',' not in match.group(0):
            issues.append((
                match.start(),
                f"{match.group(1)} requires two arguments: {match.group(1)}(list, expression)"
            ))
    
    return issues


def analyze_cel_expression(expression: str, line_offset: int = 0) -> List[types.Diagnostic]:
    """Analyze a CEL expression and return diagnostics"""
    diagnostics = []
    
    # Skip if not a CEL expression
    if not expression.strip().startswith('='):
        return diagnostics
    
    # Apply pattern-based checks
    for check in CEL_DIAGNOSTIC_PATTERNS:
        if re.search(check["pattern"], expression):
            match = re.search(check["pattern"], expression)
            if match:
                diagnostics.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line_offset, character=match.start()),
                        end=types.Position(line=line_offset, character=match.end())
                    ),
                    message=check["message"],
                    severity=check["severity"]
                ))
    
    # Check balanced brackets
    bracket_issues = check_balanced_brackets(expression)
    for pos, message in bracket_issues:
        diagnostics.append(types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line_offset, character=pos),
                end=types.Position(line=line_offset, character=pos + 1)
            ),
            message=message,
            severity=types.DiagnosticSeverity.Error
        ))
    
    # Check string interpolation
    interp_issues = check_string_interpolation(expression)
    for pos, message in interp_issues:
        diagnostics.append(types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line_offset, character=pos),
                end=types.Position(line=line_offset, character=pos + 1)
            ),
            message=message,
            severity=types.DiagnosticSeverity.Error
        ))
    
    # Check function calls
    func_issues = check_function_calls(expression)
    for pos, message in func_issues:
        diagnostics.append(types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line_offset, character=pos),
                end=types.Position(line=line_offset, character=pos + 10)
            ),
            message=message,
            severity=types.DiagnosticSeverity.Error
        ))
    
    return diagnostics


def validate_step_references(expression: str, available_steps: List[str], line_offset: int = 0) -> List[types.Diagnostic]:
    """Validate step references in expressions"""
    diagnostics = []
    
    # Find all step references
    step_refs = re.findall(r'\$\{?\s*([a-zA-Z_]\w*)\s*\}?', expression)
    
    for ref in step_refs:
        if ref not in available_steps and ref not in ['inputs', 'parent', 'self']:
            pos = expression.find(f"${ref}") if f"${ref}" in expression else expression.find(f"${{{ref}}}")
            if pos >= 0:
                diagnostics.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line_offset, character=pos),
                        end=types.Position(line=line_offset, character=pos + len(ref) + 3)
                    ),
                    message=f"Unknown step reference '{ref}'. Available steps: {', '.join(available_steps)}",
                    severity=types.DiagnosticSeverity.Error
                ))
    
    return diagnostics