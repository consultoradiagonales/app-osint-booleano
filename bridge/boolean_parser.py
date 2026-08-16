from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable, Mapping, Sequence


class BooleanSyntaxError(ValueError):
    pass


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.casefold()).strip()


class Node:
    def evaluate(self, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> bool:
        raise NotImplementedError

    def positive_terms(self, negated: bool = False) -> list[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class Term(Node):
    value: str

    def evaluate(self, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> bool:
        haystack = normalize_text(text)
        key = normalize_text(self.value)
        choices = [self.value]
        if aliases:
            for alias_key, values in aliases.items():
                if normalize_text(alias_key) == key:
                    choices.extend(values)
                    break
        # La coincidencia debe respetar palabras completas. Sin este límite,
        # `PRO` hacía entrar "proceso", "proyecto" y "profesionalizar";
        # `PJ` coincidía con fragmentos ajenos al pedido editorial.
        return any(
            re.search(rf"(?<!\w){re.escape(normalize_text(choice))}(?!\w)", haystack) is not None
            for choice in choices
            if choice.strip()
        )

    def positive_terms(self, negated: bool = False) -> list[str]:
        return [] if negated else [self.value]


@dataclass(frozen=True)
class Not(Node):
    child: Node

    def evaluate(self, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> bool:
        return not self.child.evaluate(text, aliases)

    def positive_terms(self, negated: bool = False) -> list[str]:
        return self.child.positive_terms(not negated)


@dataclass(frozen=True)
class And(Node):
    left: Node
    right: Node

    def evaluate(self, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> bool:
        return self.left.evaluate(text, aliases) and self.right.evaluate(text, aliases)

    def positive_terms(self, negated: bool = False) -> list[str]:
        return self.left.positive_terms(negated) + self.right.positive_terms(negated)


@dataclass(frozen=True)
class Or(Node):
    left: Node
    right: Node

    def evaluate(self, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> bool:
        return self.left.evaluate(text, aliases) or self.right.evaluate(text, aliases)

    def positive_terms(self, negated: bool = False) -> list[str]:
        return self.left.positive_terms(negated) + self.right.positive_terms(negated)


TOKEN_RE = re.compile(
    r'\s*(?:(?P<LPAREN>\()|(?P<RPAREN>\))|(?P<QUOTED>"(?:\\.|[^"\\])*")|'
    r'(?P<OP>\b(?:AND|OR|NOT)\b)|(?P<WORD>[^\s()]+))',
    re.IGNORECASE,
)


def normalize_editorial_query(query: str) -> str:
    """Convierte listas territoriales pegadas como frases en una expresión booleana real.

    Ejemplo: ``"Saladillo: A, B, C"`` pasa a ``("A" OR "B" OR "C")``.
    Una frase normal entre comillas no se modifica.
    """
    def replace(match: re.Match[str]) -> str:
        values = [value.strip(" \t\r\n,;\"") for value in match.group(1).split(",")]
        values = [value for value in values if value]
        if len(values) < 2:
            return match.group(0)
        return "(" + " OR ".join(f'"{value.replace(chr(34), "")}"' for value in values) + ")"

    return re.sub(r'"[^"\r\n:]{1,80}:\s*([^"\r\n]+)"', replace, query)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


def tokenize(query: str) -> list[Token]:
    if not query or not query.strip():
        raise BooleanSyntaxError("La consulta esta vacia")
    tokens: list[Token] = []
    cursor = 0
    while cursor < len(query):
        match = TOKEN_RE.match(query, cursor)
        if not match:
            raise BooleanSyntaxError(f"Token invalido cerca de: {query[cursor:cursor + 20]!r}")
        cursor = match.end()
        kind = match.lastgroup or ""
        value = match.group(kind)
        if kind == "QUOTED":
            # `unicode_escape` corrompe caracteres UTF-8 (Cámara -> CÃ¡mara),
            # dejando consultas válidas sin coincidencias. Sólo desescapamos las
            # dos secuencias admitidas dentro de una frase entre comillas.
            value = value[1:-1].replace(r'\"', '"').replace(r'\\', '\\')
            kind = "TERM"
        elif kind == "WORD":
            kind = "TERM"
        elif kind == "OP":
            kind = value.upper()
        tokens.append(Token(kind, value))
    return _insert_implicit_and(tokens)


def _insert_implicit_and(tokens: list[Token]) -> list[Token]:
    result: list[Token] = []
    ending = {"TERM", "RPAREN"}
    starting = {"TERM", "LPAREN", "NOT"}
    for token in tokens:
        if result and result[-1].kind in ending and token.kind in starting:
            result.append(Token("AND", "AND"))
        result.append(token)
    return result


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Node:
        node = self._or()
        if self.pos != len(self.tokens):
            raise BooleanSyntaxError(f"Token inesperado: {self.tokens[self.pos].value}")
        return node

    def _or(self) -> Node:
        node = self._and()
        while self._accept("OR"):
            node = Or(node, self._and())
        return node

    def _and(self) -> Node:
        node = self._not()
        while self._accept("AND"):
            node = And(node, self._not())
        return node

    def _not(self) -> Node:
        if self._accept("NOT"):
            return Not(self._not())
        return self._atom()

    def _atom(self) -> Node:
        if self._accept("LPAREN"):
            node = self._or()
            if not self._accept("RPAREN"):
                raise BooleanSyntaxError("Falta cerrar un parentesis")
            return node
        token = self._take("TERM")
        if token is None:
            current = self.tokens[self.pos].value if self.pos < len(self.tokens) else "fin de consulta"
            raise BooleanSyntaxError(f"Se esperaba un termino y se encontro {current!r}")
        return Term(token.value)

    def _accept(self, kind: str) -> bool:
        if self.pos < len(self.tokens) and self.tokens[self.pos].kind == kind:
            self.pos += 1
            return True
        return False

    def _take(self, kind: str) -> Token | None:
        if self.pos < len(self.tokens) and self.tokens[self.pos].kind == kind:
            token = self.tokens[self.pos]
            self.pos += 1
            return token
        return None


def parse(query: str) -> Node:
    return Parser(tokenize(query)).parse()


def discovery_queries(
    raw_query: str,
    root: Node,
    aliases: Mapping[str, Sequence[str]] | None = None,
    limit: int = 12,
) -> list[str]:
    """Genera pivotes reproducibles; no inventa conceptos ni usa IA."""
    candidates = [raw_query.strip()]
    terms = list(dict.fromkeys(root.positive_terms()))
    if len(terms) > 1:
        candidates.append(" ".join(f'"{term}"' if " " in term else term for term in terms))
    candidates.extend(f'"{term}"' if " " in term else term for term in terms)
    if aliases:
        for term in terms:
            normalized = normalize_text(term)
            for key, values in aliases.items():
                if normalize_text(key) == normalized:
                    candidates.extend(f'"{value}"' if " " in value else value for value in values)
    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        fingerprint = normalize_text(item)
        if item and fingerprint not in seen:
            unique.append(item)
            seen.add(fingerprint)
        if len(unique) >= limit:
            break
    return unique


def coverage(root: Node, text: str, aliases: Mapping[str, Sequence[str]] | None = None) -> float:
    """Cobertura respetando la estructura lógica: OR no penaliza sinónimos ausentes."""
    if isinstance(root, Term):
        return 1.0 if root.evaluate(text, aliases) else 0.0
    if isinstance(root, Not):
        return 1.0
    if isinstance(root, And):
        return (coverage(root.left, text, aliases) + coverage(root.right, text, aliases)) / 2
    if isinstance(root, Or):
        return max(coverage(root.left, text, aliases), coverage(root.right, text, aliases))
    raise TypeError(type(root))


def ast_dict(node: Node) -> dict:
    if isinstance(node, Term):
        return {"term": node.value}
    if isinstance(node, Not):
        return {"not": ast_dict(node.child)}
    if isinstance(node, And):
        return {"and": [ast_dict(node.left), ast_dict(node.right)]}
    if isinstance(node, Or):
        return {"or": [ast_dict(node.left), ast_dict(node.right)]}
    raise TypeError(type(node))
