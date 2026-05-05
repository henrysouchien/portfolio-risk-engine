from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import sqlite3

from core.corpus.section_map import edgar_id_to_corpus_header


class PredicateError(ValueError):
    """Raised on tokenize/parse/allow-list/compile failure."""


class TokenType(StrEnum):
    IDENT = 'ident'
    STRING_LIT = 'string'
    INT_LIT = 'int'
    OP_EQ = 'op_eq'
    OP_LE = 'op_le'
    KW_IN = 'kw_in'
    KW_IS = 'kw_is'
    KW_NULL = 'kw_null'
    KW_NOT = 'kw_not'
    KW_AND = 'kw_and'
    KW_OR = 'kw_or'
    KW_LIKE = 'kw_like'
    LPAREN = 'lparen'
    RPAREN = 'rparen'
    COMMA = 'comma'
    EOF = 'eof'


DOCUMENT_COLUMNS = frozenset(
    'ticker form_type fiscal_period cik parser_version parser_schema_version '
    'parser_path parser_state parser_result_status cross_reference_target '
    'producer_deployment_id producer_instance_id producer_build_id'.split()
)
SECTION_COLUMNS = frozenset('section_key word_count text'.split())
ALLOWED_COLUMNS = DOCUMENT_COLUMNS | SECTION_COLUMNS
_KEYWORDS = dict(
    IN=TokenType.KW_IN,
    IS=TokenType.KW_IS,
    NULL=TokenType.KW_NULL,
    NOT=TokenType.KW_NOT,
    AND=TokenType.KW_AND,
    OR=TokenType.KW_OR,
    LIKE=TokenType.KW_LIKE,
)
_RESERVED_KEYWORDS = frozenset(
    'SELECT FROM WHERE LIKE BETWEEN EXISTS DROP DELETE INSERT UPDATE CREATE ALTER '
    'TABLE UNION JOIN ORDER GROUP HAVING LIMIT OFFSET'.split()
)
_ILLEGAL = ('--', '/*', '*/', '||', ';', '`')
_SINGLE_CHAR_TOKENS = {'=': TokenType.OP_EQ, '(': TokenType.LPAREN, ')': TokenType.RPAREN, ',': TokenType.COMMA}
_SECTION_FORM_TYPES = ('10-K', '10-Q', '8-K')
_WORD_COUNT_FUNCTION = 'corpus_section_word_count'
_WORD_COUNT_RE = re.compile(r'^\*\*Word count:\*\*\s*([0-9][0-9,]*)\s*$', re.MULTILINE)


@dataclass(frozen=True)
class _Token:
    type: TokenType
    value: object
    position: int

@dataclass(frozen=True)
class Comparison:
    column: str
    value: object

@dataclass(frozen=True)
class LessEqual:
    column: str
    value: object

@dataclass(frozen=True)
class Like:
    column: str
    value: object

@dataclass(frozen=True)
class InList:
    column: str
    values: tuple[object, ...]

@dataclass(frozen=True)
class IsNull:
    column: str
    negated: bool

@dataclass(frozen=True)
class BinaryOp:
    op: TokenType
    left: object
    right: object

@dataclass(frozen=True)
class _Compiled:
    sql: str
    params: list
    section_only: bool


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
        if self.text.startswith('<=', self.pos):
            self.pos += 2
            return _Token(TokenType.OP_LE, '<=', start)
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
        if self._match(TokenType.OP_LE):
            return LessEqual(column, self._literal())
        if self._match(TokenType.KW_LIKE):
            return Like(column, self._literal())
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
        raise PredicateError(f'expected =, <=, LIKE, IN, or IS after {column!r}; got {self._describe(self.token)}')
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
    compiled = _compile(_Parser(_Tokenizer(where_clause)).parse())
    if compiled.section_only:
        return _section_filter_sql(compiled.sql), compiled.params
    return compiled.sql, compiled.params


def _compile(node: object) -> _Compiled:
    if isinstance(node, Comparison):
        return _compile_comparison(node)
    if isinstance(node, LessEqual):
        return _compile_less_equal(node)
    if isinstance(node, Like):
        return _compile_like(node)
    if isinstance(node, InList):
        return _compile_in_list(node)
    if isinstance(node, IsNull):
        if node.column not in DOCUMENT_COLUMNS:
            raise PredicateError(f'operator IS NULL is not allowed for column {node.column!r}')
        return _Compiled(f'{node.column} IS {"NOT " if node.negated else ""}NULL', [], False)
    if isinstance(node, BinaryOp):
        return _compile_binary(node)
    raise PredicateError(f'unsupported predicate node {type(node).__name__}')


def _compile_comparison(node: Comparison) -> _Compiled:
    if node.column in DOCUMENT_COLUMNS:
        return _Compiled(f'{node.column} = ?', [node.value], False)
    if node.column == 'section_key':
        return _section_key_predicate(node.value)
    if node.column == 'word_count':
        _require_int(node.value, node.column, '=')
        return _Compiled(f'{_WORD_COUNT_FUNCTION}(s.content) = ?', [node.value], True)
    raise PredicateError(f"operator '=' is not allowed for column {node.column!r}")


def _compile_less_equal(node: LessEqual) -> _Compiled:
    if node.column != 'word_count':
        raise PredicateError(f"operator '<=' is not allowed for column {node.column!r}")
    _require_int(node.value, node.column, '<=')
    return _Compiled(f'{_WORD_COUNT_FUNCTION}(s.content) <= ?', [node.value], True)


def _compile_like(node: Like) -> _Compiled:
    if node.column != 'text':
        raise PredicateError(f"operator LIKE is not allowed for column {node.column!r}")
    _require_str(node.value, node.column, 'LIKE')
    return _Compiled('s.content LIKE ?', [node.value], True)


def _compile_in_list(node: InList) -> _Compiled:
    if node.column in DOCUMENT_COLUMNS:
        return _Compiled(f'{node.column} IN ({", ".join("?" for _ in node.values)})', list(node.values), False)
    if node.column == 'section_key':
        headers: list[str] = []
        for value in node.values:
            headers.extend(_section_headers_for_key(value))
        headers = list(dict.fromkeys(headers))
        return _Compiled(f's.section IN ({", ".join("?" for _ in headers)})', headers, True)
    raise PredicateError(f'operator IN is not allowed for column {node.column!r}')


def _compile_binary(node: BinaryOp) -> _Compiled:
    op = 'AND' if node.op == TokenType.KW_AND else 'OR'
    terms = [_compile(term) for term in _flatten_binary(node, node.op)]
    if all(term.section_only for term in terms):
        return _join_compiled(terms, op, section_only=True)

    outer_terms: list[_Compiled] = []
    section_terms: list[_Compiled] = []
    section_insert_index: int | None = None
    for term in terms:
        if term.section_only:
            if node.op == TokenType.KW_AND:
                section_insert_index = len(outer_terms) if section_insert_index is None else section_insert_index
                section_terms.append(term)
            else:
                outer_terms.append(_Compiled(_section_filter_sql(term.sql), term.params, False))
        else:
            outer_terms.append(term)

    if section_terms:
        section_group = _join_compiled(section_terms, 'AND', section_only=True)
        exists_term = _Compiled(_section_filter_sql(section_group.sql), section_group.params, False)
        outer_terms.insert(section_insert_index if section_insert_index is not None else len(outer_terms), exists_term)
    return _join_compiled(outer_terms, op, section_only=False)


def _flatten_binary(node: object, op: TokenType) -> list[object]:
    if isinstance(node, BinaryOp) and node.op == op:
        return [*_flatten_binary(node.left, op), *_flatten_binary(node.right, op)]
    return [node]


def _join_compiled(terms: list[_Compiled], op: str, *, section_only: bool) -> _Compiled:
    if not terms:
        raise PredicateError('empty predicate expression')
    if len(terms) == 1:
        return _Compiled(terms[0].sql, list(terms[0].params), section_only)
    sql = f'({f" {op} ".join(term.sql for term in terms)})'
    params = [param for term in terms for param in term.params]
    return _Compiled(sql, params, section_only)


def _section_filter_sql(section_sql: str) -> str:
    return f'documents.document_id IN (SELECT s.document_id FROM sections_fts s WHERE ({section_sql}))'


def _section_key_predicate(value: object) -> _Compiled:
    headers = _section_headers_for_key(value)
    if len(headers) == 1:
        return _Compiled('s.section = ?', [headers[0]], True)
    return _Compiled(f's.section IN ({", ".join("?" for _ in headers)})', list(headers), True)


def _section_headers_for_key(value: object) -> tuple[str, ...]:
    _require_str(value, 'section_key', '=')
    key = str(value).strip()
    if not key:
        raise PredicateError('section_key must not be empty')
    headers = tuple(
        dict.fromkeys(
            header
            for form_type in _SECTION_FORM_TYPES
            if (header := edgar_id_to_corpus_header(key, form_type)) is not None
        )
    )
    if not headers:
        raise PredicateError(f'unknown section_key {key!r}')
    return headers


def _require_int(value: object, column: str, operator: str) -> None:
    if not isinstance(value, int):
        raise PredicateError(f'operator {operator} on column {column!r} requires an int literal')


def _require_str(value: object, column: str, operator: str) -> None:
    if not isinstance(value, str):
        raise PredicateError(f'operator {operator} on column {column!r} requires a string literal')


def section_word_count(content: object) -> int:
    if not isinstance(content, str):
        raise ValueError('section content must be text')
    matches = _WORD_COUNT_RE.findall(content)
    if len(matches) != 1:
        raise ValueError('section content must contain exactly one **Word count:** marker')
    return int(matches[0].replace(',', ''))


def register_predicate_functions(db: sqlite3.Connection) -> None:
    try:
        db.create_function(_WORD_COUNT_FUNCTION, 1, section_word_count, deterministic=True)
    except sqlite3.NotSupportedError:
        db.create_function(_WORD_COUNT_FUNCTION, 1, section_word_count)


__all__ = [
    'ALLOWED_COLUMNS',
    'DOCUMENT_COLUMNS',
    'SECTION_COLUMNS',
    'PredicateError',
    'TokenType',
    'compile_predicate',
    'register_predicate_functions',
    'section_word_count',
]
