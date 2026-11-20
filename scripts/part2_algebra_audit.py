"""Offline symbolic check of written equations and inequalities in the static atlas.

Run with uv run --isolated --no-project --with sympy==1.14.0
--with antlr4-python3-runtime==4.11.1 python scripts/part2_algebra_audit.py.
No symbolic solver is required by the bot.
"""

import json
import re
from pathlib import Path

import sympy as sp
from sympy.calculus.util import continuous_domain
from sympy.parsing.latex import parse_latex

ATLAS = Path(__file__).resolve().parents[1] / "atlas/part2/tasks.jsonl"
X, Y = sp.symbols("x y")


def formulas(text):
    return re.findall(r"\\\((.*?)\\\)", text, re.S)


def expression(tex):
    # Expand single-token TeX arguments for the symbolic parser.
    tex = tex.strip().replace(r"\ ", "").replace("{,}", ".")
    tex = re.sub(r"\\sqrt(\d)", r"\\sqrt{\1}", tex)
    tex = re.sub(r"\\frac(\d)([a-z])", r"\\frac{\1}{\2}", tex)
    return parse_latex(tex, strict=True)


def answer_set(tex):
    components = []
    for part in tex.removeprefix(r"x\in").split(r"\cup"):
        if part.startswith(r"\{"):
            components.append(
                sp.FiniteSet(*(sp.simplify(expression(x)) for x in re.split("[;,]", part[2:-2])))
            )
        elif part.startswith(("(", "[")):
            left, right = part[1:-1].split(";")
            components.append(
                sp.Interval(
                    sp.simplify(expression(left)),
                    sp.simplify(expression(right)),
                    part[0] == "(",
                    part[-1] == ")",
                )
            )
        else:
            components.append(sp.FiniteSet(sp.simplify(expression(part.removeprefix("x=")))))
    return sp.Union(*components)


def compare(card):
    statement = formulas(card["statement"])[-1].replace(r"\left", "").replace(r"\right", "")
    statement = statement.replace("x(", r"x\cdot (")
    answer = formulas(card["answer_or_claim"])
    if r"\begin{cases}" in statement:
        equations = []
        for equation in (
            statement.removeprefix(r"\begin{cases}").removesuffix(r"\end{cases}").split(r"\\")
        ):
            left, right = equation.strip(" ,.").split("=")
            equations.append(expression(left) - expression(right))
        roots = sp.solve(equations, [X, Y], set=True)[1]
        actual = sp.FiniteSet(*(sp.Tuple(*r) for r in roots if all(v.is_real for v in r)))
        pairs = ";".join(answer).replace(r"\left", "").replace(r"\right", "").replace(r"\ ", "")
        expected = sp.FiniteSet(
            *(
                sp.Tuple(*(sp.simplify(expression(v)) for v in re.split("[;,]", pair)))
                for pair in re.findall(r"\(([^()]+)\)", pairs)
            )
        )
    else:
        left, op, right = re.split(r"(=|\\le(?![A-Za-z])|\\ge(?![A-Za-z])|<|>)", statement)
        left, right = expression(left), expression(right)
        domain = continuous_domain(left, X, sp.S.Reals) & continuous_domain(right, X, sp.S.Reals)
        if op == "=":
            actual = sp.solveset(left - right, X, domain=domain)
        else:
            relation = {r"\le": sp.Le, r"\ge": sp.Ge, "<": sp.Lt, ">": sp.Gt}[op](left, right)
            actual = sp.solve_univariate_inequality(relation, X, relational=False) & domain
        expected = sp.Union(*(answer_set(item) for item in answer))
    if actual != expected:
        raise ValueError(f"{card['task_id']}: computed {actual}, atlas {expected}")


if __name__ == "__main__":
    cards = [
        c for line in ATLAS.read_text().splitlines() if (c := json.loads(line))["number"] == 20
    ]
    for card in cards:
        compare(card)
    print(f"Verified {len(cards)} real solution sets directly from statements")
