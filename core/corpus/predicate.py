from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PredicateError(ValueError):
    """Raised on tokenize/parse/allow-list/compile failure."""


class TokenType(StrEnum):
    IDENT = 'ident'; STRING_LIT = 'string'; INT_LIT = 'int'; OP_EQ = 'op_eq'
    KW_IN = 'kw_in'; KW_IS = 'kw_is'; KW_NULL = 'kw_null'; KW_NOT = 'kw_not'
    KW_AND = 'kw_and'; KW_OR = 'kw_or'
    LPAREN = 'lparen'; RPAREN = 'rparen'; COMMA = 'comma'; EOF = 'eof'


ALLOWED_COLUMNS = frozenset(
    'ticker form_type fiscal_period cik parser_version parser_schema_version '
    'parser_path parser_state parser_result_status cross_reference_target '
    'producer_deployment_id producer_instance_id producer_build_id'.split()
)
_KEYWORDS = dict(IN=TokenType.KW_IN, IS=TokenType.KW_IS, NULL=TokenType.KW_NULL, NOT=TokenType.KW_NOT, AND=TokenType.KW_AND, OR=TokenType.KW_OR)
_RESERVED_KEYWORDS = frozenset(
    'SELECT FROM WHERE LIKE BETWEEN EXISTS DROP DELETE INSERT UPDATE CREATE ALTER '
    'TABLE UNION JOIN ORDER GROUP HAVING LIMIT OFFSET'.split()
)
_ILLEGAL = ('--', '/*', '*/', '||', ';', '`')
_SINGLE_CHAR_TOKENS = {'=': TokenType.OP_EQ, '(': TokenType.LPAREN, ')': TokenType.RPAREN, ',': TokenType.COMMA}


@dataclass(frozen=True)
class _Token:
    type: TokenType; value: object; position: int

@dataclass(frozen=True)
class Comparison:
    column: str; value: object

@dataclass(frozen=True)
class InList:
    column: str; values: tuple[object, ...]

@dataclass(frozen=True)
class IsNull:
    column: str; negated: bool

@dataclass(frozen=True)
class BinaryOp:
    op: TokenType; left: object; right: object


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
    def next_token(self) -> _Token:
        self._skip_space()
        if self.pos >= len(self.text):
            return _Token(TokenType.EOF, '', self.pos)
        for illegal in _ILLEGAL:
            if self.text.startswith(illegal, self.pos):
                raise self._error(f'illegal token {illegal!r}')
        char = self.text[self.pos]
        start = self.pos
        if char == "'":
            return self._read_string()
        if char.isdigit():
            return self._read_int()
        if char.isalpha() or char == '_':
            return self._read_word()
        if char in _SINGLE_CHAR_TOKENS:
            self.pos += 1
            return _Token(_SINGLE_CHAR_TOKENS[char], char, start)
        raise self._error(f'illegal character {char!r}')
    def _skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
    def _read_string(self) -> _Token:
        start = self.pos
        self.pos += 1
        chars: list[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "'":
                if self.pos + 1 < len(self.text) and self.text[self.pos + 1] == "'":
                    chars.append("'")
                    self.pos += 2
                    continue
                self.pos += 1
                return _Token(TokenType.STRING_LIT, ''.join(chars), start)
            chars.append(char)
            self.pos += 1
        raise PredicateError(f'unterminated string literal at position {start}')
    def _read_int(self) -> _Token:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        return _Token(TokenType.INT_LIT, int(self.text[start : self.pos]), start)
    def _read_word(self) -> _Token:
        start = self.pos
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == '_'):
            self.pos += 1
        word = self.text[start : self.pos]
        return _Token(_KEYWORDS.get(word.upper(), TokenType.IDENT), word, start)
    def _error(self, message: str) -> PredicateError:
        return PredicateError(f'{message} at position {self.pos}')


class _Parser:
    def __init__(self, tokenizer: _Tokenizer) -> None:
        self.tokenizer = tokenizer
        self.token = tokenizer.next_token()
    def parse(self) -> object:
        expression = self._or()
        if self.token.type != TokenType.EOF:
            raise PredicateError(f'unexpected trailing token {self._describe(self.token)}')
        return expression
    def _or(self) -> object:
        expression = self._and()
        while self._match(TokenType.KW_OR):
            expression = BinaryOp(TokenType.KW_OR, expression, self._and())
        return expression
    def _and(self) -> object:
        expression = self._atom()
        while self._match(TokenType.KW_AND):
            expression = BinaryOp(TokenType.KW_AND, expression, self._atom())
        return expression
    def _atom(self) -> object:
        if self._match(TokenType.LPAREN):
            expression = self._or()
            self._expect(TokenType.RPAREN)
            return expression
        return self._predicate()
    def _predicate(self) -> object:
        column = self._column()
        if self._match(TokenType.OP_EQ):
            return Comparison(column, self._literal())
        if self._match(TokenType.KW_IN):
            self._expect(TokenType.LPAREN)
            values = [self._literal()]
            while self._match(TokenType.COMMA):
                values.append(self._literal())
            self._expect(TokenType.RPAREN)
            return InList(column, tuple(values))
        if self._match(TokenType.KW_IS):
            negated = self._match(TokenType.KW_NOT)
            self._expect(TokenType.KW_NULL)
            return IsNull(column, negated)
        self._reject_reserved(self.token)
        raise PredicateError(f'expected =, IN, or IS after {column!r}; got {self._describe(self.token)}')
    def _column(self) -> str:
        if self.token.type != TokenType.IDENT:
            self._reject_reserved(self.token)
            raise PredicateError(f'expected column name; got {self._describe(self.token)}')
        token = self.token
        self._advance()
        name = str(token.value)
        if name.upper() in _RESERVED_KEYWORDS:
            raise PredicateError(f'unsupported keyword {name!r} at position {token.position}')
        if name not in ALLOWED_COLUMNS:
            raise PredicateError(f'column {name!r} is not allowed')
        return name
    def _literal(self) -> object:
        if self.token.type not in {TokenType.STRING_LIT, TokenType.INT_LIT}:
            self._reject_reserved(self.token)
            raise PredicateError(f'expected string or int literal; got {self._describe(self.token)}')
        value = self.token.value
        self._advance()
        return value
    def _match(self, token_type: TokenType) -> bool:
        if self.token.type != token_type:
            return False
        self._advance()
        return True
    def _expect(self, token_type: TokenType) -> None:
        if self.token.type != token_type:
            self._reject_reserved(self.token)
            raise PredicateError(f'expected {token_type.value}; got {self._describe(self.token)}')
        self._advance()
    def _advance(self) -> None:
        self.token = self.tokenizer.next_token()
    @staticmethod
    def _reject_reserved(token: _Token) -> None:
        if token.type == TokenType.IDENT and str(token.value).upper() in _RESERVED_KEYWORDS:
            raise PredicateError(f'unsupported keyword {token.value!r} at position {token.position}')
    @staticmethod
    def _describe(token: _Token) -> str:
        if token.type == TokenType.EOF:
            return 'end of input'
        return f'{token.value!r} at position {token.position}'


def compile_predicate(where_clause: str) -> tuple[str, list]:
    """Compile a YAML ``where`` fragment to parameterized SQL and params."""
    if not isinstance(where_clause, str):
        raise PredicateError(f'where_clause must be str, got {type(where_clause).__name__}')
    return _compile(_Parser(_Tokenizer(where_clause)).parse())


def _compile(node: object) -> tuple[str, list]:
    if isinstance(node, Comparison):
        return f'{node.column} = ?', [node.value]
    if isinstance(node, InList):
        return f'{node.column} IN ({", ".join("?" for _ in node.values)})', list(node.values)
    if isinstance(node, IsNull):
        return f'{node.column} IS {"NOT " if node.negated else ""}NULL', []
    if isinstance(node, BinaryOp):
        left_sql, left_params = _compile(node.left)
        right_sql, right_params = _compile(node.right)
        op = 'AND' if node.op == TokenType.KW_AND else 'OR'
        return f'({left_sql} {op} {right_sql})', [*left_params, *right_params]
    raise PredicateError(f'unsupported predicate node {type(node).__name__}')


__all__ = ['ALLOWED_COLUMNS', 'PredicateError', 'TokenType', 'compile_predicate']
