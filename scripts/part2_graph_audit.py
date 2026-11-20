"""Offline exact intersection audit of the plotted branches (same QA environment as algebra)."""

import json
import re

import sympy as sp
from part2_algebra_audit import ATLAS, X, answer_set, expression, formulas


def targets(statement):
    if any(word in statement for word in ("максимальн", "наибольш", "самое большее")):
        return None
    for phrase, counts in [
        ("одну или две", {1, 2}),
        ("двух точках", {2}),
        ("две общие", {2}),
        ("три общие", {3}),
        ("одну общую", {1}),
        ("одна общая", {1}),
        ("не имеют", {0}),
        ("нет общих", {0}),
        ("не встречается", {0}),
    ]:
        if phrase in statement:
            return counts
    raise ValueError("Unknown question about intersections")


def intersection_cells(card):
    statement = card["statement"]
    slope = "y=kx" in statement
    shift = re.search(r"y=a([+-]\d+)", statement)
    offset = int(shift[1]) if shift else 0
    # Each monotone open arc contributes one preimage throughout its open range.
    # Shared included endpoints are counted only once by their coordinates.
    arcs = []
    points = set()
    flat = set()
    origin = False
    for branch in card["visuals"][0]["construction"]["branches"]:
        expr = branch["expression"]
        if not re.fullmatch(r"[x0-9\s+*/^()-]+", expr):
            raise ValueError(f"Unsupported plotted expression: {expr}")
        f = sp.sympify(expr, locals={"x": X})
        d = branch["domain"]
        lo = sp.Rational(d["lower"]) if d["lower"] is not None else -sp.oo
        hi = sp.Rational(d["upper"]) if d["upper"] is not None else sp.oo
        domain = sp.Interval(lo, hi, not d["lower_inclusive"], not d["upper_inclusive"])
        if slope and 0 in domain and f.subs(X, 0) == 0:
            origin = True
        parameter = sp.cancel(f / X) if slope else f - offset
        extrema = sp.solve(sp.diff(parameter, X), X)
        splits = sorted({lo, hi, *[z for z in extrema if z.is_real and lo < z < hi]})
        if slope and lo < 0 < hi and 0 not in splits:
            splits = sorted([*splits, sp.Integer(0)])
        for z in splits:
            if z in domain and not (slope and z == 0):
                points.add((z, parameter.subs(X, z)))
        for start, end in zip(splits, splits[1:], strict=False):
            a = sp.limit(parameter, X, start, dir="+")
            b = sp.limit(parameter, X, end, dir="-")
            if a == b:
                flat.add(a)
            else:
                arcs.append(sp.Interval.open(min(a, b), max(a, b)))
    breaks = sorted(
        {
            -sp.oo,
            sp.oo,
            *[v for _, v in points],
            *flat,
            *(v for arc in arcs for v in (arc.start, arc.end)),
        }
    )

    def count(v):
        if v in flat:
            return sp.oo
        return (
            int(origin) + sum(1 for _, y in points if y == v) + sum(1 for arc in arcs if v in arc)
        )

    cells = [(sp.FiniteSet(v), count(v)) for v in breaks if v.is_finite]
    for a, b in zip(breaks, breaks[1:], strict=False):
        probe = (
            (a + b) / 2
            if a.is_finite and b.is_finite
            else (b - 1 if b.is_finite else a + 1 if a.is_finite else 0)
        )
        cells.append((sp.Interval.open(a, b), count(probe)))
    return cells


def compare(card):
    cells = intersection_cells(card)
    wanted = targets(card["statement"])
    raw = formulas(card["answer_or_claim"])[0]
    if wanted is None:
        actual = max(n for _, n in cells)
        expected = expression(raw)
    else:
        actual = sp.Union(*(region for region, count in cells if count in wanted))
        expected = answer_set(re.sub(r"^[amkc](?:\\in|=)", "", raw))
    if actual != expected:
        raise ValueError(f"{card['task_id']}: intersection audit found {actual}, atlas {expected}")


if __name__ == "__main__":
    cards = [
        c for line in ATLAS.read_text().splitlines() if (c := json.loads(line))["number"] == 22
    ]
    for card in cards:
        compare(card)
    print(f"Verified parameter answers from plotted branches for {len(cards)} graph cards")
