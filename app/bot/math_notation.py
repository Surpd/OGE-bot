"""Lossless source spans and a deliberately small, non-evaluating display grammar.

No substitution over mathematical strings: every candidate must parse completely.
Unknown/ambiguous notation remains literal. Original spans reconstruct the input.
"""

import re
from dataclasses import dataclass
from html import escape

_SUPER = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+", strict=True))
_SUB = dict(zip("₀₁₂₃₄₅₆₇₈₉ₙ", "0123456789n", strict=True))
_SIGNS = {
    "−": "-",
    "·": r"\cdot",
    "×": r"\times",
    ":": r"\div",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "∞": r"\infty",
    "∈": r"\in",
    "∪": r"\cup",
    "<=": r"\leq",
    ">=": r"\geq",
    "!=": r"\neq",
}
_GREEK = {"α": r"\alpha", "β": r"\beta", "ρ": r"\rho", "ω": r"\omega", "π": r"\pi", "φ": r"\varphi"}
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" + "".join(_GREEK)
_CHARS = set(_LETTERS + "0123456789., +-−*/·×:^_=<>!≤≥≠()[];√∞∈∪" + "".join(_SUPER) + "".join(_SUB))
_RICH_UNSAFE_DENOMINATOR_PRODUCT = re.compile(
    r"/\(\s*[+\-−]?\d+(?:[.,]\d+)?\s*(?:[A-Za-zαβρπωφ]|\()"
)


@dataclass(frozen=True)
class Span:
    source: str
    latex: str | None = None


class _Parser:
    def __init__(self, source: str):
        self.tokens: list[str] = []
        self.index = 0
        pos = 0
        while pos < len(source):
            char = source[pos]
            if char.isspace():
                pos += 1
                continue
            start = pos
            if char.isascii() and char.isalpha():
                word_end = pos
                while (
                    word_end < len(source)
                    and source[word_end].isascii()
                    and source[word_end].isalpha()
                ):
                    word_end += 1
                if word_end - pos > 2 and source[pos:word_end] not in {"sin", "cos"}:
                    raise ValueError("Unrecognized word")
            if char.isascii() and char.isdigit():
                pos += 1
                while pos < len(source) and source[pos].isascii() and source[pos].isdigit():
                    pos += 1
                if (
                    pos + 1 < len(source)
                    and source[pos] in ".,"
                    and source[pos + 1].isascii()
                    and source[pos + 1].isdigit()
                ):
                    pos += 2
                    while pos < len(source) and source[pos].isascii() and source[pos].isdigit():
                        pos += 1
            elif source[pos:pos + 2] in {"<=", ">=", "!="}:
                pos += 2
            elif source.startswith("sin", pos) or source.startswith("cos", pos):
                pos += 3
            else:
                pos += 1
            self.tokens.append(source[start:pos])
        if len(self.tokens) > 180:
            raise ValueError("Expression too long")

    def peek(self) -> str:
        return self.tokens[self.index] if self.index < len(self.tokens) else ""

    def pop(self) -> str:
        token = self.peek()
        if not token:
            raise ValueError("Missing operand")
        self.index += 1
        return token

    def expression(self, depth: int = 0) -> str:
        if depth > 20:
            raise ValueError("Expression too deep")
        left = self.product(depth + 1)
        while self.peek() in {
            "+", "-", "−", "=", "<", ">", "<=", ">=", "!=", "≤", "≥", "≠", "∈", "∪"
        }:
            sign = self.pop()
            left += " " + _SIGNS.get(sign, sign) + " " + self.product(depth + 1)
        return left

    def product(self, depth: int) -> str:
        left = self.unary(depth)
        divided = False
        while True:
            token = self.peek()
            if token in {"*", "·", "×", "/", ":"}:
                self.pop()
                right = self.unary(depth)
                if token == "/":
                    left = rf"\frac{{{left}}}{{{right}}}"
                    divided = True
                else:
                    left += " " + _SIGNS.get(token, r"\cdot") + " " + right
            elif token and (
                token[0].isascii() and token[0].isalnum() or token in _GREEK or token in {"(", "√"}
            ):
                # a/bc has ambiguous denominator scope; retain the entire span.
                if divided:
                    raise ValueError("Implicit multiplication after division")
                if (
                    token[0].isascii()
                    and token[0].isdigit()
                    and (
                        self.tokens[self.index - 1][0].isdigit()
                        or self.tokens[self.index - 1] in _LETTERS
                    )
                ):
                    raise ValueError("Mixed number or ambiguous identifier")
                # School notation uses juxtaposition for algebraic products:
                # 2x, xy, and 2(x+3). Keep only explicitly written products
                # (handled above) as a multiplication sign.
                left += self.unary(depth)
            else:
                return left

    def unary(self, depth: int) -> str:
        if self.peek() in {"+", "-", "−"}:
            return _SIGNS.get(sign := self.pop(), sign) + self.unary(depth + 1)
        return self.power(depth)

    def power(self, depth: int) -> str:
        base = self.atom(depth)
        if self.peek() == "_":
            self.pop()
            base += "_{" + self.atom(depth + 1) + "}"
        elif self.peek() in _SUB:
            suffix = ""
            while self.peek() in _SUB:
                suffix += _SUB[self.pop()]
            base += "_{" + suffix + "}"
        if self.peek() == "^":
            self.pop()
            base = "{" + base + "}^{" + self.power(depth + 1) + "}"
        elif self.peek() in _SUPER:
            suffix = ""
            while self.peek() in _SUPER:
                suffix += _SUPER[self.pop()]
            base = "{" + base + "}^{" + suffix + "}"
        return base

    def atom(self, depth: int) -> str:
        if depth > 20:
            raise ValueError("Expression too deep")
        token = self.pop()
        if token in {"(", "["}:
            content = self.expression(depth + 1)
            if self.peek() == ";":
                self.pop()
                content += "; " + self.expression(depth + 1)
                close = self.pop()
                if close not in {")", "]"}:
                    raise ValueError("Unclosed interval")
            else:
                close = self.pop()
                if close != (")" if token == "(" else "]"):
                    raise ValueError("Unclosed parentheses")
            return rf"\left{token}{content}\right{close}"
        if token == "√":
            grouped = self.peek() == "("
            radicand = self.atom(depth + 1)
            if not grouped and self.peek() in {"^", *_SUPER}:
                raise ValueError("Unbounded radical scope")
            return r"\sqrt{" + radicand + "}"
        if token in {"sin", "cos"}:
            return "\\" + token + " " + self.atom(depth + 1)
        if token in _GREEK or token == "∞":
            return _GREEK.get(token, _SIGNS.get(token, token))
        if len(token) == 1 and token in _LETTERS:
            return token
        if token[0].isascii() and token[0].isdigit():
            # Braces suppress decimal-comma punctuation spacing, retaining zeros.
            return token.replace(",", "{,}")
        raise ValueError("Unknown mathematical token")


def parse_formula(source: str) -> str | None:
    try:
        parser = _Parser(source)
        latex = parser.expression()
        if parser.peek():
            return None
        return latex
    except (ValueError, RecursionError):
        return None


def rich_needs_png_fallback(source: str | object) -> bool:
    """Avoid Telegram Rich Math for rational denominators with implicit products.

    Telegram's Rich renderer has displayed the variable twice for forms such
    as ``1/(2x)``. Route only those expressions through our deterministic
    local raster renderer; ordinary juxtaposition remains native Rich math.
    """
    if not isinstance(source, str):
        return False
    return any(
        span.latex is not None and _RICH_UNSAFE_DENOMINATOR_PRODUCT.search(span.source)
        for span in math_spans(source)
    )


def math_spans(source: str) -> list[Span]:
    """Partition text exactly; accept only complete bounded grammar candidates."""
    spans: list[Span] = []
    pos = 0
    while pos < len(source):
        start = pos
        mathematical = source[pos] in (_CHARS - set(" .,*/·×:^_=<>!≤≥≠]);∈∪"))
        if mathematical:
            while pos < len(source) and source[pos] in _CHARS:
                # Sentence punctuation is not a decimal separator.
                if source[pos] in ".," and not (
                    pos > start
                    and source[pos - 1].isascii()
                    and source[pos - 1].isdigit()
                    and pos + 1 < len(source)
                    and source[pos + 1].isascii()
                    and source[pos + 1].isdigit()
                ):
                    break
                pos += 1
            end = pos
            while end > start and source[end - 1] == " ":
                end -= 1
            if end > start:
                candidate = source[start:end]
                spans.append(Span(candidate, parse_formula(candidate)))
                if end < pos:
                    spans.append(Span(source[end:pos]))
                continue
        # Include at least one character even when punctuation stopped a span.
        pos = max(start + 1, pos)
        while pos < len(source) and (source[pos] not in _CHARS or source[pos] == " "):
            pos += 1
        spans.append(Span(source[start:pos]))
    assert "".join(span.source for span in spans) == source
    return spans


def rich_inline(source: str) -> str:
    return "".join(
        # Telegram's rich renderer currently duplicates infinity glyphs when
        # it receives the LaTeX command. Keep interval text literal so each
        # visible Unicode ∞ is sent exactly once.
        escape(span.source)
        if "∞" in span.source
        else "<tg-math>" + escape(span.latex) + "</tg-math>"
        if span.latex is not None
        else escape(span.source)
        for span in math_spans(source)
    )
