from typing import NamedTuple
import re

from .semantics import (
    Modifier,
    NodeDiagnostic,
    SemanticNode,
    Position,
    Severity,
    TokenType,
)

SYMBOL = re.compile(r"[\w]+")
QUOTED = re.compile(r"(?P<quote>['\"])(?P<string>.*?)(?P=quote)")
OP = re.compile(r"->|[\{\}\(\)\.,+:*-=\[\]^$!<>|?&\\]")
SPACE = re.compile(r"\s+")

NUMBER = re.compile(r"\d+")

KEYWORDS = {"has", "all", "exists", "exists_one", "map", "filter"}


class Token(NamedTuple):
    position: Position
    start_rel: Position

    text: str

    token_type: TokenType
    token_modifiers: list[Modifier]


def is_dquote(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == '"' and token.token_type == "operator"


def is_squote(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == "'" and token.token_type == "operator"


def is_lparen(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == "(" and token.token_type == "operator"


def is_lbrace(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == "{" and token.token_type == "operator"


def is_rbrace(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == "}" and token.token_type == "operator"


def is_colon(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == ":" and token.token_type == "operator"


def is_comma(token: Token | None) -> bool:
    if token is None:
        return False

    return token.text == "," and token.token_type == "operator"


def parse(
    cel_expression: list[str],
    anchor_base_pos: Position,
    seed_line: int = 0,
    seed_offset: int = 0,
    abs_offset: int = 0,
) -> list[SemanticNode]:
    """Convert the given expression into a list of tokens"""
    tokens = lex(
        cel_expression=cel_expression,
        seed_line=seed_line,
        seed_offset=seed_offset,
        abs_offset=abs_offset,
    )

    return _extract_semantic_structure(tokens, anchor_base_pos)


def _extract_semantic_structure(
    tokens: list[Token], anchor_base_pos: Position
) -> list[SemanticNode]:
    """Given a list of tokens, determine their type and modifiers."""

    def next(idx):
        """Get the next token, if possible"""
        if idx >= len(tokens) - 1:
            return None

        return tokens[idx + 1]

    in_brace = False
    in_dquote = False
    in_squote = False

    nodes: list[SemanticNode] = []
    for idx, token in enumerate(tokens):
        if token.token_type == "operator":
            node_diagnostic = None
            if is_lbrace(token):
                in_brace = True

            elif is_rbrace(token):
                in_brace = False

            elif is_dquote(token):
                in_dquote = not in_dquote

            elif is_squote(token):
                in_squote = not in_squote

            elif is_comma(token) and is_rbrace(next(idx)):
                node_diagnostic = NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                )

            nodes.append(
                SemanticNode(
                    position=token.position,
                    anchor_rel=Position(
                        line=token.start_rel.line + anchor_base_pos.line,
                        character=token.start_rel.character,
                    ),
                    length=len(token.text),
                    node_type=token.token_type,
                    modifier=token.token_modifiers,
                    diagnostic=node_diagnostic,
                )
            )

            continue

        token_type = ""
        if in_dquote or in_squote:
            if is_colon(next(idx + 1)) and in_brace:
                token_type = "property"
            else:
                token_type = "string"

        elif token.text in KEYWORDS:
            token_type = "keyword"

        elif is_lparen(next(idx)):
            token_type = "function"

        else:
            if NUMBER.match(token.text):
                token_type = "number"
            else:
                token_type = "variable"

        nodes.append(
            SemanticNode(
                position=token.position,
                anchor_rel=Position(
                    line=token.start_rel.line + anchor_base_pos.line,
                    character=token.start_rel.character,
                ),
                length=len(token.text),
                node_type=token_type,
                modifier=token.token_modifiers,
            )
        )

    return nodes


def lex(
    cel_expression: list[str],
    seed_line: int = 0,
    seed_offset: int = 0,
    abs_offset: int = 0,
) -> list[Token]:
    """Convert the given document into a list of tokens"""
    tokens = []

    prev_line = 0

    for current_line, line in enumerate(cel_expression, start=seed_line):
        prev_offset = 0
        current_offset = seed_offset
        chars_left = len(line)

        if not line.strip():
            seed_offset = 0
            continue

        while line:
            if (match := SPACE.match(line)) is not None:
                # Skip whitespace
                current_offset += len(match.group(0))
                line = line[match.end() :]

            elif (match := QUOTED.match(line)) is not None:
                quote_group_len = len(match.group("quote"))
                string_len = len(match.group("string"))

                tokens.append(
                    Token(
                        position=Position(
                            line=current_line - prev_line,
                            character=current_offset - prev_offset,
                        ),
                        start_rel=Position(
                            line=current_line,
                            character=abs_offset + current_offset,
                        ),
                        text=match.group("quote"),
                        token_type="operator",
                        token_modifiers=[],
                    ),
                )

                if string_len:
                    tokens.append(
                        Token(
                            position=Position(line=0, character=quote_group_len),
                            start_rel=Position(
                                line=current_line,
                                character=abs_offset + current_offset + quote_group_len,
                            ),
                            text=match.group("string"),
                            token_type="string",
                            token_modifiers=[],
                        )
                    )

                tokens.append(
                    Token(
                        position=Position(
                            line=0,
                            character=string_len if string_len else quote_group_len,
                        ),
                        start_rel=Position(
                            line=current_line,
                            character=abs_offset
                            + current_offset
                            + quote_group_len
                            + string_len,
                        ),
                        text=match.group("quote"),
                        token_type="operator",
                        token_modifiers=[],
                    ),
                )

                line = line[match.end() :]
                prev_line = current_line
                # First quote + quoted string
                current_offset += quote_group_len + string_len
                prev_offset = current_offset
                # Closing quote
                current_offset += quote_group_len

            elif (match := SYMBOL.match(line)) is not None:
                tokens.append(
                    Token(
                        position=Position(
                            line=current_line - prev_line,
                            character=current_offset - prev_offset,
                        ),
                        start_rel=Position(
                            line=current_line,
                            character=abs_offset + current_offset,
                        ),
                        text=match.group(0),
                        token_type="",
                        token_modifiers=[],
                    )
                )

                line = line[match.end() :]
                prev_offset = current_offset
                prev_line = current_line
                current_offset += len(match.group(0))

            elif (match := OP.match(line)) is not None:
                tokens.append(
                    Token(
                        position=Position(
                            line=current_line - prev_line,
                            character=current_offset - prev_offset,
                        ),
                        start_rel=Position(
                            line=current_line,
                            character=abs_offset + current_offset,
                        ),
                        text=match.group(0),
                        token_type="operator",
                        token_modifiers=[],
                    )
                )

                line = line[match.end() :]
                prev_offset = current_offset
                prev_line = current_line
                current_offset += len(match.group(0))

            else:
                raise RuntimeError(f"No match: {line!r}")

            # Make sure we don't hit an infinite loop
            if (n := len(line)) == chars_left:
                raise RuntimeError("Inifite loop detected")
            else:
                chars_left = n

        prev_line = current_line
        seed_offset = 0
        abs_offset = 0

    return tokens
