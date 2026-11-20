"""Evaluate plotted expressions and finite endpoints independently using exact arithmetic."""

import ast
import json
import operator
from fractions import Fraction

from app.persistence.part2_bank import ATLAS

_OPERATIONS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def _value(node, x):
    if isinstance(node, ast.Name) and node.id == "x":
        return x
    if isinstance(node, ast.Constant):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_value(node.operand, x)
    if isinstance(node, ast.BinOp):
        return _OPERATIONS[type(node.op)](_value(node.left, x), _value(node.right, x))
    raise ValueError("Unsupported expression in graph")


def test_graph_markers_lie_on_the_right_branches():
    for line in (ATLAS / "tasks.jsonl").read_text().splitlines():
        card = json.loads(line)
        if card["number"] != 22:
            continue
        graph = card["visuals"][0]["construction"]
        for kind in ("open_points", "marked_included_points", "turning_points"):
            for point in graph.get(kind, []):
                x, y = Fraction(point["x"]), Fraction(point["y"])
                endpoints = set()
                included = set()
                for branch in graph["branches"]:
                    d = branch["domain"]
                    lo = Fraction(d["lower"]) if d["lower"] is not None else None
                    hi = Fraction(d["upper"]) if d["upper"] is not None else None
                    if lo is not None and x < lo or hi is not None and x > hi:
                        continue
                    expr = ast.parse(branch["expression"].replace("^", "**"), mode="eval").body
                    try:
                        value = _value(expr, x)
                    except ZeroDivisionError:
                        continue
                    endpoints.add(value)
                    if (x != lo or d["lower_inclusive"]) and (x != hi or d["upper_inclusive"]):
                        included.add(value)
                assert y in endpoints, (card["task_id"], point)
                assert (y in included) == (kind != "open_points"), (card["task_id"], point)
