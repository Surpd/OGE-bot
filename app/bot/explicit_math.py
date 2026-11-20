"""Display-only TeX for the versioned written-work atlas and tutor feedback."""

import re
from collections.abc import Iterator

DELIMITERS = re.compile(
    r"\\\((.*?)\\\)|\\\[(.*?)\\\]|\$\$([^$]+)\$\$|(?<!\$)\$([^$\n]+)\$",
    re.DOTALL,
)
CASES = re.compile(r"(.*?)\\begin\{cases\}(.*?)\\end\{cases\}(.*)", re.DOTALL)
TOKEN = re.compile(r"\\[a-zA-Z]+|\\.|.")
LOCAL_COMMANDS = {
    r"\le": r"\leq",
    r"\ge": r"\geq",
    r"\ne": r"\neq",
    r"\dfrac": r"\frac",
    r"\emptyset": r"\varnothing",
}
SYMBOLS = {
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "cdot": "·",
    "times": "×",
    "angle": "∠",
    "circ": "°",
    "triangle": "△",
    "in": "∈",
    "sim": "∼",
    "perp": "⊥",
    "parallel": "∥",
    "infty": "∞",
    "cup": "∪",
    "emptyset": "∅",
    "varnothing": "∅",
    "pm": "±",
    "alpha": "α",
    "beta": "β",
    "to": "→",
    "Rightarrow": "⇒",
    "quad": "  ",
    "qquad": "    ",
    "left": "",
    "right": "",
    ",": " ",
    ";": " ",
    "!": "",
    "\\": "  ",
    " ": " ",
}
SUPERSCRIPT = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
SUBSCRIPT = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉₊₋")


def formulas(source: str) -> Iterator[tuple[int, int, str]]:
    for match in DELIMITERS.finditer(source):
        yield match.start(), match.end(), next(s.strip() for s in match.groups() if s is not None)


def case_parts(latex: str) -> tuple[str, tuple[tuple[str, ...], ...], str] | None:
    match = CASES.fullmatch(latex)
    if match is None:
        return None
    left, body, right = match.groups()
    rows = tuple(tuple(cell.strip() for cell in row.split("&")) for row in body.split(r"\\"))
    return left.strip(), rows, right.strip()


def local_tex(latex: str) -> str:
    tokens: list[str] = TOKEN.findall(latex)
    pos = 0

    def argument() -> str:
        nonlocal pos
        while pos < len(tokens) and tokens[pos].isspace():
            pos += 1
        if pos == len(tokens):
            return ""
        if tokens[pos] != "{":
            return "{" + token() + "}"
        pos += 1
        parts = []
        while pos < len(tokens) and tokens[pos] != "}":
            parts.append(token())
        if pos < len(tokens):
            pos += 1
        return "{" + "".join(parts) + "}"

    def token() -> str:
        nonlocal pos
        value = tokens[pos]
        pos += 1
        normalized = LOCAL_COMMANDS.get(value, value)
        if normalized == r"\frac":
            return normalized + argument() + argument()
        if normalized == r"\sqrt" and pos < len(tokens) and tokens[pos] != "[":
            return normalized + argument()
        if value == "{":
            pos -= 1
            return argument()
        return normalized

    result = []
    while pos < len(tokens):
        result.append(token())
    return "".join(result)


def plain_tex(latex: str) -> str:
    """Readable grouped notation, also used if a provider supplies unsupported TeX."""
    cases = case_parts(latex)
    if cases:
        left, rows, right = cases
        return (
            plain_tex(left)
            + " { "
            + "  ;  ".join("  ".join(map(plain_tex, row)) for row in rows)
            + " } "
            + plain_tex(right)
        ).strip()

    tokens: list[str] = TOKEN.findall(latex)
    position = 0

    def argument(depth: int) -> str:
        nonlocal position
        if position >= len(tokens):
            return ""
        char = tokens[position]
        position += 1
        if depth > 32:
            return char.removeprefix("\\")
        if char == "{":
            return group(depth + 1, True)
        if char in (r"\frac", r"\dfrac", r"\tfrac"):
            return f"({argument(depth + 1)})/({argument(depth + 1)})"
        if char == r"\sqrt":
            return f"√({argument(depth + 1)})"
        if char in "^_":
            value = argument(depth + 1)
            if value and all(c in "0123456789+-" for c in value):
                return value.translate(SUPERSCRIPT if char == "^" else SUBSCRIPT)
            return f"{char}({value})"
        if char.startswith("\\"):
            return SYMBOLS.get(char[1:], char[1:])
        return {"-": "−", "&": " ", "}": ""}.get(char, char)

    def group(depth: int, closing: bool = False) -> str:
        nonlocal position
        pieces = []
        while position < len(tokens):
            if closing and tokens[position] == "}":
                position += 1
                break
            if (
                tokens[position] == " "
                and position + 1 < len(tokens)
                and tokens[position + 1] == "}"
            ):
                position += 1
                continue
            pieces.append(argument(depth))
        return "".join(pieces)

    return group(0)


def plain_text(source: str) -> str:
    parts: list[str] = []
    previous = 0
    for start, end, latex in formulas(source):
        parts.extend((source[previous:start], plain_tex(latex)))
        previous = end
    parts.append(source[previous:])
    return "".join(parts)


def display_feedback(source: str) -> str:
    """Repair bare TeX from generated feedback using grouped, readable notation."""
    # Delimited math is handled by presentation. A bare command has no reliable
    # formula boundary, so only its own arguments are decoded here.
    result: list[str] = []
    previous = 0
    for start, end, _ in formulas(source):
        prefix = source[previous:start]
        result.extend((plain_tex(prefix) if "\\" in prefix else prefix, source[start:end]))
        previous = end
    tail = source[previous:]
    result.append(plain_tex(tail) if "\\" in tail else tail)
    return "".join(result)
