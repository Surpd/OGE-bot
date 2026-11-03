"""Explicit mathematical presentation nodes, independent of generation and checking.

Only callers that already know the mathematical structure may construct nodes.
Never parse or rewrite a validated snapshot to infer that structure.
"""

from dataclasses import dataclass
from typing import Literal, Protocol


class MathFragment(Protocol):
    def unicode(self) -> str: ...

    def latex(self) -> str: ...


def _latex_token(text: str) -> str:
    # Tokens are data, never arbitrary LaTeX commands. Text mode also preserves
    # decimal commas, Unicode signs, spaces, and literal underscores/carets.
    escapes = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "~": r"\textasciitilde{}",
    }
    return r"\text{" + "".join(escapes.get(char, char) for char in text) + "}"


@dataclass(frozen=True)
class MathToken:
    """An exact literal token; no normalization, arithmetic, or source parsing."""

    text: str

    def unicode(self) -> str:
        return self.text

    def latex(self) -> str:
        return _latex_token(self.text)


@dataclass(frozen=True)
class Fraction:
    numerator: MathFragment
    denominator: MathFragment

    def unicode(self) -> str:
        return f"({self.numerator.unicode()})/({self.denominator.unicode()})"

    def latex(self) -> str:
        return rf"\frac{{{self.numerator.latex()}}}{{{self.denominator.latex()}}}"


_SUPERSCRIPTS = str.maketrans("0123456789−-+()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁻⁺⁽⁾")


@dataclass(frozen=True)
class Power:
    base: MathFragment
    exponent: MathFragment

    def unicode(self) -> str:
        exponent = self.exponent.unicode()
        if (
            isinstance(self.exponent, MathToken)
            and exponent
            and all(char in "0123456789−-+()" for char in exponent)
        ):
            suffix = exponent.translate(_SUPERSCRIPTS)
        else:
            suffix = f"^({exponent})"
        return f"({self.base.unicode()}){suffix}"

    def latex(self) -> str:
        return rf"\left({self.base.latex()}\right)^{{{self.exponent.latex()}}}"


@dataclass(frozen=True)
class Root:
    radicand: MathFragment
    index: MathFragment | None = None

    def unicode(self) -> str:
        if self.index is None:
            return f"√({self.radicand.unicode()})"
        index = self.index.unicode()
        if isinstance(self.index, MathToken) and index and index.isascii() and index.isdigit():
            return f"{index.translate(_SUPERSCRIPTS)}√({self.radicand.unicode()})"
        return f"√[{index}]({self.radicand.unicode()})"

    def latex(self) -> str:
        index = "" if self.index is None else f"[{self.index.latex()}]"
        return rf"\sqrt{index}{{{self.radicand.latex()}}}"


@dataclass(frozen=True)
class Operation:
    left: MathFragment
    operator: Literal["+", "−", "×"]
    right: MathFragment

    def __post_init__(self) -> None:
        if self.operator not in {"+", "−", "×"}:
            raise ValueError("Unsupported mathematical operation")

    def unicode(self) -> str:
        return f"({self.left.unicode()}) {self.operator} ({self.right.unicode()})"

    def latex(self) -> str:
        operator = {"+": "+", "−": "-", "×": r"\cdot"}[self.operator]
        return rf"\left({self.left.latex()}\right) {operator} \left({self.right.latex()}\right)"


@dataclass(frozen=True)
class Comparison:
    left: MathFragment
    sign: Literal["<", "≤", "=", "≠", "≥", ">"]
    right: MathFragment

    def __post_init__(self) -> None:
        if self.sign not in {"<", "≤", "=", "≠", "≥", ">"}:
            raise ValueError("Unsupported comparison sign")

    def unicode(self) -> str:
        return f"{self.left.unicode()} {self.sign} {self.right.unicode()}"

    def latex(self) -> str:
        sign = {"≤": r"\le", "≥": r"\ge", "≠": r"\ne"}.get(self.sign, self.sign)
        return f"{self.left.latex()} {sign} {self.right.latex()}"


@dataclass(frozen=True)
class System:
    rows: tuple[MathFragment, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("A system needs at least one row")

    def unicode(self) -> str:
        return "{ " + "\n  ".join(row.unicode() for row in self.rows)

    def latex(self) -> str:
        return r"\begin{cases}" + r" \\ ".join(row.latex() for row in self.rows) + r"\end{cases}"


@dataclass(frozen=True)
class Interval:
    lower: MathFragment
    upper: MathFragment
    lower_closed: bool = False
    upper_closed: bool = False

    def unicode(self) -> str:
        left = "[" if self.lower_closed else "("
        right = "]" if self.upper_closed else ")"
        return f"{left}{self.lower.unicode()}; {self.upper.unicode()}{right}"

    def latex(self) -> str:
        left = "[" if self.lower_closed else "("
        right = "]" if self.upper_closed else ")"
        return f"{left}{self.lower.latex()}; {self.upper.latex()}{right}"


@dataclass(frozen=True)
class Progression:
    """Explicit arithmetic-progression formula; never compute its values."""

    first: MathFragment
    difference: MathFragment
    index: MathFragment

    def unicode(self) -> str:
        return (
            f"{self._term_label()} = ({self.first.unicode()}) + "
            f"(({self.index.unicode()}) − 1) × ({self.difference.unicode()})"
        )

    def _term_label(self) -> str:
        index = self.index.unicode()
        return "aₙ" if index == "n" else f"a[{index}]"

    def latex(self) -> str:
        return (
            rf"a_{{{self.index.latex()}}} = \left({self.first.latex()}\right) + "
            rf"\left(({self.index.latex()}) - 1\right) \cdot "
            rf"\left({self.difference.latex()}\right)"
        )
