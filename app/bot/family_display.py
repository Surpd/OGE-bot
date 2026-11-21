"""Stable transport preference for identified mathematical templates."""

import json
import re
from functools import lru_cache
from pathlib import Path

from app.bot.learner_math import learner_text


@lru_cache(maxsize=1)
def formats() -> dict[str, str]:
    data: dict[str, str] = json.loads(Path(__file__).with_name("template_formats.json").read_text())
    return data


def template_key(source: object) -> str | None:
    if isinstance(source, dict):
        source = source.get("subtype_id") or source.get("family_id")
    return source if isinstance(source, str) and source in formats() else None


def template_format(source: object) -> str | None:
    key = template_key(source)
    return formats()[key] if key is not None else None


def typeset_mixed_number(text: str, source: object) -> str:
    """In F006 a whole number and the following fraction denote a mixed number."""
    from app.bot.math_notation import parse_formula

    family = source.get("family_id") if isinstance(source, dict) else source
    if family != "OGE06-F006-MIXED-MINUS-DECIMAL":
        return text

    def convert(match: re.Match[str]) -> str:
        whole, numerator, denominator, op, rhs = match.groups()
        mixed = rf"{whole}\frac{{{numerator}}}{{{denominator}}}"
        if op and rhs:
            mixed += " " + op.replace("−", "-") + " " + (parse_formula(rhs) or rhs)
        return rf"\({mixed}\)"

    return re.sub(
        r"(?<![\d/])(\d+) (1)/(2)(?![\d/])(?:\s*([−=\-])\s*(\d+(?:[,.]\d+|/\d+)?))?",
        convert,
        text,
    )


def typeset_family_text(text: str, source: object) -> str:
    """Recover a bounded quotient inside prose when the enclosing line is not a formula."""
    from app.bot.math_notation import math_spans, parse_formula

    if not source:
        return text
    text = typeset_mixed_number(text, source)
    family = (source.get("subtype_id") or source.get("family_id")
              if isinstance(source, dict) else source)
    if isinstance(family, str):
        text = learner_text(text, family)
    if isinstance(family, str) and family.startswith("OGE11-"):
        if isinstance(source, dict) and source.get("generator_version") == "0.2.0":
            previous = source.get("solution")
            if (
                isinstance(previous, list)
                and previous
                and all(isinstance(s, str) for s in previous)
                and previous[0] in text
            ):
                from fractions import Fraction

                from app.math.oge11 import Graph, graph_solution

                graphs = tuple(
                    Graph(g["kind"], tuple(map(Fraction, g["coefficients"])))
                    for g in source["graphs"]
                )
                updated = graph_solution(
                    graphs,
                    tuple(source["letter_graph_ids"]),
                    tuple(source["digit_graph_ids"]),
                    source["answer_kind"],
                )
                old = "\n".join(previous)
                text = text.replace(old, "\n".join(updated))
        text = re.sub(r"/\((\d+)x\)", r"/(\1·x)", text)
    if isinstance(family, str) and family.startswith("TYRES-"):
        return text
    if family == "OGE14-A02" and isinstance(source, dict) and "aₙ = aⱼ" in text:
        p = source.get("parameters")
        if isinstance(p, dict) and all(isinstance(p.get(k), int) for k in ("a1", "j", "d", "rows")):
            seats = p["a1"] + (p["j"] - 1) * p["d"]
            text = text.replace(
                f"aₙ = aⱼ + ({p['rows']}−{p['j']})d",
                f"От ряда {p['j']} до последнего — ещё "
                f"{p['rows']} − {p['j']} переходов. "
                f"aₙ = {seats} + ({p['rows']} − {p['j']}) · {p['d']}",
            )
    if family == "OGE16-D04":
        text = text.replace("AB/(2 sin C)", r"\(\frac{AB}{2\cdot\sin C}\)")
        text = re.sub(
            r"(\d+)√2/\(2 · sin 45°\)",
            lambda m: rf"\(\frac{{{m[1]}\sqrt{{2}}}}{{2\cdot\sin 45^\circ}}\)",
            text,
        )
    if family == "OGE09-K3":
        # Historical K3 snapshots substituted a negative b without parentheses.
        text = re.sub(r"(D = b² − 4ac = )(-\d+)²(?= − 4·)", r"\1(\2)²", text)
    if family == "OGE09-K3" or family == "OGE09-K2":

        def root_quotient(match: re.Match[str]) -> str:
            latex = parse_formula(match[0])
            return rf"\({latex}\)" if latex else match[0]

        text = re.sub(r"\([^()]*\([−-]?\d+\)[^()]*\)/\([−\d·*-]+\)", root_quotient, text)
    parts = []
    # Segment labels contain two capital letters. Do not reinterpret units, tyre codes,
    # slash-separated words, or an unparenthesized algebraic denominator such as a/bc.
    operand = r"(?:(?:[A-Z][₀-₉]?){2}[²³]?|r[₀-₉]|\d+(?:[,.]\d+)?(?:\^\d+|[²³])?|[xy])"
    quotient = rf"(?<![\w/√])({operand})\s*/\s*({operand})(?![\w/^(²³])"
    for span in math_spans(text):
        value = span.source
        if span.latex or "/" not in value:
            parts.append(value)
            continue
        if family == "OGE24-similar-parallels":
            value = re.sub(
                r"\(([A-Z]{2})\s*[−-]\s*([A-Z]{2})\)\s*/\s*([A-Z]{2})(?!\w)",
                r"\\(\\frac{\1-\2}{\3}\\)",
                value,
            )
        if family == "OGE24-midline-proof":
            value = re.sub(
                r"S\(([A-Z]{3})\)\s*/\s*(\d+)(?![\w/])",
                r"\\(\\frac{S(\1)}{\2}\\)",
                value,
            )
        if isinstance(family, str) and family.startswith("OGE11-"):
            # Graph.formula emits rational coefficients as p/q followed by x.
            # Its inverse graphs always parenthesize a product in the denominator.
            value = re.sub(r"(?<![\w/])(\d+/\d+)(?=x)", r"(\1)", value)
            prefix, marker, expression = value.partition("y=")
            parsed = parse_formula(marker + expression) if marker else parse_formula(value)
            if parsed:
                parts.append((prefix if marker else "") + rf"\({parsed}\)")
                continue

        def replace(match: re.Match[str]) -> str:
            top, bottom = match.groups()
            num = parse_formula(top)
            den = parse_formula(bottom)
            if not num or not den:
                return match[0]
            return rf"\(\frac{{{num}}}{{{den}}}\)"

        parts.append(re.sub(quotient, replace, value))
    return "".join(parts)
