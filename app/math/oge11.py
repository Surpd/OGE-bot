"""Deterministic OGE task 11 graph and coefficient matching problems.

The runtime gate lists only families that passed the independent source-image
audit and the generator acceptance checks.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import permutations
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.math.oge11_render import render_graphs

GENERATOR_VERSION = "0.2.0"
RENDERER_VERSION = "0.3.0"
POLICY_ID = "oge11.three-digit-bijection"
POLICY_VERSION = "1"
FAMILIES = tuple(f"OGE11-F{i:02d}" for i in range(1, 9))
ENABLED_FAMILIES: tuple[str, ...] = FAMILIES
REFERENCE_IDS = {
    "OGE11-F01": ("339085", "349265"),
    "OGE11-F02": ("FIPI-DEMO-2027-11", "340583"),
    "OGE11-F03": ("341702",),
    "OGE11-F04": ("348381",),
    "OGE11-F05": ("349706",),
    "OGE11-F06": ("350104", "350202"),
    "OGE11-F07": ("340835",),
    "OGE11-F08": ("341668",),
}
MAX_CANDIDATES = 1200
_LETTERS = ("А", "Б", "В")
_DIGITS = ("1", "2", "3")

# Independent visible-condition contract: (answer kind, exact first line).
_VISIBLE_TASK_CONTRACTS = {
    "OGE11-F01": ("formula_letters", "Соотнесите формулы А, Б, В с графиками 1, 2, 3:"),
    "OGE11-F02": ("formula_options", "Соотнесите графики А, Б, В с формулами из списка 1, 2, 3:"),
    "OGE11-F03": ("signs", "Соотнесите графики А, Б, В со знаками коэффициентов k и b:"),
    "OGE11-F04": (
        "signs_letters",
        "Соотнесите знаки коэффициентов с графиками 1, 2, 3:",
    ),
    "OGE11-F05": ("formula_letters", "Соотнесите формулы А, Б, В с графиками 1, 2, 3:"),
    "OGE11-F06": ("formula_letters", "Соотнесите формулы А, Б, В с графиками 1, 2, 3:"),
    "OGE11-F07": (
        "formula_options",
        "Соотнесите графики А, Б, В с формулами из списка 1, 2, 3:",
    ),
    "OGE11-F08": ("formula_letters", "Соотнесите формулы А, Б, В с графиками 1, 2, 3:"),
}

_EXPECTED_HINTS = {
    "OGE11-F01": (
        "Сначала определите вид графика или формулы.",
        "Проверьте контрольные точки и внесите соответствия по порядку А, Б, В.",
    ),
    "OGE11-F02": (
        "Сначала определите вид каждого графика.",
        "Проверьте контрольные точки и внесите соответствия по порядку А, Б, В.",
    ),
    "OGE11-F03": (
        "Знак k задаёт направление прямой; знак b — её пересечение с Oy, то есть y(0).",
        "Сопоставьте графики А, Б, В с вариантами знаков 1, 2, 3.",
    ),
    "OGE11-F04": (
        "Знак a задаёт направление ветвей; c — значение y(0), точка пересечения с Oy.",
        "Сопоставьте пары знаков с параболами и запишите номера графиков в порядке А, Б, В.",
    ),
    "OGE11-F05": (
        "У прямой через начало координат знак и величину наклона показывает её направление.",
        "Сопоставьте формулы А, Б, В с графиками 1, 2, 3.",
    ),
    "OGE11-F06": (
        "Сравните наклон прямой и её значение y(0).",
        "Сопоставьте формулы А, Б, В с графиками 1, 2, 3.",
    ),
    "OGE11-F07": (
        "Горизонтальный график задаёт постоянную функцию.",
        "Сопоставьте графики А, Б, В с формулами 1, 2, 3.",
    ),
    "OGE11-F08": (
        "У y=q/x ветви лежат в I и III четвертях при q>0, во II и IV при q<0.",
        "Сравните четверти и контрольные точки, затем сопоставьте формулы "
        "А, Б, В с графиками 1, 2, 3.",
    ),
}


@dataclass(frozen=True, slots=True)
class Graph:
    kind: str
    coefficients: tuple[Fraction, ...]

    def value(self, x: Fraction) -> Fraction:
        if self.kind == "linear":
            k, b = self.coefficients
            return k * x + b
        if self.kind == "quadratic":
            a, b, c = self.coefficients
            return a * x * x + b * x + c
        if self.kind == "inverse":
            (q,) = self.coefficients
            if x == 0:
                raise ValueError("inverse function is undefined at x=0")
            return q / x
        if self.kind == "constant":
            (c,) = self.coefficients
            return c
        raise ValueError(f"Unsupported graph kind: {self.kind}")

    def formula(self) -> str:
        if self.kind == "linear":
            k, b = self.coefficients
            return f"y={_term(k, 'x')}{_signed(b)}"
        if self.kind == "quadratic":
            a, b, c = self.coefficients
            return f"y={_term(a, 'x²')}{_signed(b, 'x')}{_signed(c)}"
        if self.kind == "inverse":
            (q,) = self.coefficients
            if q.denominator == 1:
                return f"y={_fraction_text(q)}/x"
            return f"y={q.numerator}/({q.denominator}x)"
        (c,) = self.coefficients
        return f"y={_fraction_text(c)}"

    def as_json(self) -> dict[str, object]:
        return {"kind": self.kind, "coefficients": [_fraction_text(v) for v in self.coefficients]}


@dataclass(frozen=True, slots=True)
class Oge11Problem:
    problem_id: str
    seed: int
    family_id: str
    generator_version: str
    renderer_version: str
    condition: str
    graphs: tuple[Graph, Graph, Graph]
    graph_order: tuple[int, int, int]
    graph_labels: tuple[str, str, str]
    letter_graph_ids: tuple[int, int, int]
    digit_graph_ids: tuple[int, int, int]
    answer_kind: str
    options: tuple[str, str, str]
    correct_answer: str
    hints: tuple[str, str]
    solution: tuple[str, ...]
    png_bytes: bytes
    image_sha256: str
    viewport: tuple[Fraction, Fraction, Fraction, Fraction]
    fingerprint: str
    generation_attempts: int = 1

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "family_id": self.family_id,
            "reference_ids": list(REFERENCE_IDS[self.family_id]),
            "generator_version": self.generator_version,
            "renderer_version": self.renderer_version,
            "condition": self.condition,
            "graphs": [graph.as_json() for graph in self.graphs],
            "graph_order": list(self.graph_order),
            "graph_labels": list(self.graph_labels),
            "letter_graph_ids": list(self.letter_graph_ids),
            "digit_graph_ids": list(self.digit_graph_ids),
            "answer_kind": self.answer_kind,
            "options": list(self.options),
            "answer_policy_id": POLICY_ID,
            "answer_policy_version": POLICY_VERSION,
            "correct_answer": self.correct_answer,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "png_base64": __import__("base64").b64encode(self.png_bytes).decode("ascii"),
            "image_sha256": self.image_sha256,
            "viewport": [_fraction_text(value) for value in self.viewport],
            "fingerprint": self.fingerprint,
            "generation_attempts": self.generation_attempts,
        }


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _term(value: Fraction, symbol: str = "") -> str:
    magnitude = abs(value)
    coeff = "" if symbol and magnitude == 1 else _fraction_text(magnitude)
    return f"{'-' if value < 0 else ''}{coeff}{symbol}"


def _signed(value: Fraction, symbol: str = "") -> str:
    return ("+" if value >= 0 else "-") + _term(abs(value), symbol)


def _linear(k: int | Fraction, b: int | Fraction) -> Graph:
    return Graph("linear", (Fraction(k), Fraction(b)))


def _quadratic(a: int | Fraction, b: int | Fraction, c: int | Fraction) -> Graph:
    if not a:
        raise ValueError("quadratic coefficient a must be non-zero")
    return Graph("quadratic", (Fraction(a), Fraction(b), Fraction(c)))


def _inverse(q: int | Fraction) -> Graph:
    if not q:
        raise ValueError("inverse coefficient q must be non-zero")
    return Graph("inverse", (Fraction(q),))


def _parse_formula(text: str) -> Graph:
    """Independent parser for the exact short formula language shown in captions."""
    source = text.replace(" ", "").replace("−", "-")
    match = re.fullmatch(r"y=([+-]?(?:\d+(?:/\d+)?)?)x([+-]\d+(?:/\d+)?)", source)
    if match:
        coefficient = match[1]
        k = (
            Fraction(-1 if coefficient == "-" else 1)
            if coefficient in {"", "+", "-"}
            else Fraction(coefficient)
        )
        return _linear(k, Fraction(match[2]))
    match = re.fullmatch(
        r"y=([+-]?(?:\d+(?:/\d+)?)?)x²([+-]?(?:\d+(?:/\d+)?)?)x([+-]\d+(?:/\d+)?)", source
    )
    if match:
        a_text, b_text, c_text = match.groups()
        a = Fraction(-1 if a_text == "-" else 1) if a_text in {"", "+", "-"} else Fraction(a_text)
        b = (
            Fraction(-1 if b_text == "-" else 1)
            if b_text in {"", "+", "-"}
            else (
                Fraction(-1 if b_text == "-" else 1) if b_text in {"+", "-"} else Fraction(b_text)
            )
        )
        return _quadratic(a, b, Fraction(c_text))
    match = re.fullmatch(r"y=([+-]?\d+(?:/\d+)?)/x", source)
    if match:
        return _inverse(Fraction(match[1]))
    match = re.fullmatch(r"y=([+-]?\d+)/\((\d+)x\)", source)
    if match:
        return _inverse(Fraction(int(match[1]), int(match[2])))
    match = re.fullmatch(r"y=([+-]?\d+(?:/\d+)?)", source)
    if match:
        return Graph("constant", (Fraction(match[1]),))
    raise ValueError(f"Unsupported visible formula: {text}")


def _validate_graphs(graphs: tuple[Graph, Graph, Graph]) -> None:
    if len({(g.kind, g.coefficients) for g in graphs}) != 3:
        raise ValueError("three different mathematical graphs are required")
    for graph in graphs:
        if graph.kind == "inverse" and graph.coefficients[0] == 0:
            raise ValueError("inverse coefficient cannot be zero")
        if graph.kind == "quadratic" and graph.coefficients[0] == 0:
            raise ValueError("quadratic coefficient cannot be zero")


def _random_graph(
    family_id: str,
    rng: random.Random,
    index: int = 0,
    sign_pairs: tuple[tuple[int, int], ...] | None = None,
) -> Graph:
    if family_id in {"OGE11-F01", "OGE11-F02"}:
        constructors = (
            lambda: _linear(
                rng.choice((-3, -2, -1, Fraction(-1, 2), Fraction(1, 2), 1, 2, 3)),
                rng.randint(-3, 3),
            ),
            lambda: _quadratic(
                rng.choice((-2, -1, Fraction(-1, 2), Fraction(1, 2), 1, 2)),
                rng.randint(-3, 3),
                rng.randint(-3, 3),
            ),
            lambda: _inverse(rng.choice((-9, -6, -4, -2, -1, 1, 2, 4, 6, 9))),
        )
        return constructors[index]()
    if family_id == "OGE11-F03":
        signs = sign_pairs or rng.sample(((-1, -1), (-1, 1), (1, -1), (1, 1)), 3)
        ksign, bsign = signs[index]
        return _linear(ksign * rng.choice((1, Fraction(1, 2), 2, 3)), bsign * rng.randint(1, 4))
    if family_id == "OGE11-F04":
        signs = sign_pairs or rng.sample(((-1, -1), (-1, 1), (1, -1), (1, 1)), 3)
        asign, csign = signs[index]
        return _quadratic(
            asign * rng.choice((Fraction(1, 2), 1, 2)),
            rng.randint(-2, 2),
            csign * rng.randint(1, 3),
        )
    if family_id == "OGE11-F05":
        slope = rng.choice(
            (-3, -2, -1, Fraction(-1, 2), Fraction(-1, 3), Fraction(1, 3), Fraction(1, 2), 1, 2, 3)
        )
        return _linear(slope, 0)
    if family_id == "OGE11-F06":
        return _linear(rng.choice((-3, -2, -1, 1, 2, 3)), rng.randint(-4, 4))
    if family_id == "OGE11-F07":
        if index == 0:
            return Graph("constant", (Fraction(rng.choice((-3, -2, -1, 1, 2, 3))),))
        return _linear(rng.choice((-3, -2, -1, 1, 2, 3)), rng.randint(-3, 3))
    if family_id == "OGE11-F08":
        return _inverse(
            rng.choice(
                (
                    Fraction(-2),
                    Fraction(-1),
                    Fraction(-1, 2),
                    Fraction(1, 2),
                    Fraction(1),
                    Fraction(2),
                )
            )
        )
    raise ValueError(f"Unknown task-11 family: {family_id}")


def _format_condition(
    family: str,
    graphs: tuple[Graph, Graph, Graph],
    order: tuple[int, int, int],
    answer_kind: str | None = None,
) -> tuple[str, str, tuple[str, str, str]]:
    if family == "OGE11-F03":
        ordered = tuple(graphs[index] for index in order)
        options = tuple(
            f"k {'+' if g.coefficients[0] > 0 else '−'}, b {'+' if g.coefficients[1] > 0 else '−'}"
            for g in ordered
        )
        text = "Соотнесите графики А, Б, В со знаками коэффициентов k и b:\n" + "\n".join(
            f"{i + 1}) {option}" for i, option in enumerate(options)
        )
        return text, "signs", cast(tuple[str, str, str], options)
    if family == "OGE11-F04":
        ordered = tuple(graphs[index] for index in order)
        options = tuple(
            f"a {'>' if g.coefficients[0] > 0 else '<'} 0, "
            f"c {'>' if g.coefficients[2] > 0 else '<'} 0"
            for g in ordered
        )
        text = "Соотнесите знаки коэффициентов с графиками 1, 2, 3:\n" + "\n".join(
            f"{_LETTERS[i]}) {option}" for i, option in enumerate(options)
        )
        return text, "signs_letters", cast(tuple[str, str, str], options)
    formula_map = {index: graphs[index].formula() for index in range(3)}
    if answer_kind == "formula_options" or family in {"OGE11-F02", "OGE11-F07"}:
        numbered = tuple(formula_map[index] for index in order)
        return (
            "Соотнесите графики А, Б, В с формулами из списка 1, 2, 3:\n"
            + "\n".join(f"{i + 1}) {formula}" for i, formula in enumerate(numbered)),
            "formula_options",
            cast(tuple[str, str, str], numbered),
        )
    formulas = tuple(formula_map[index] for index in order)
    return (
        "Соотнесите формулы А, Б, В с графиками 1, 2, 3:\n"
        + "\n".join(f"{_LETTERS[i]}) {formula}" for i, formula in enumerate(formulas)),
        "formula_letters",
        cast(tuple[str, str, str], formulas),
    )


def _expected_hints(family_id: str, answer_kind: str) -> tuple[str, str]:
    hints = _EXPECTED_HINTS[family_id]
    if family_id == "OGE11-F06":
        direction = (
            "Сопоставьте графики А, Б, В с формулами 1, 2, 3."
            if answer_kind == "formula_options"
            else "Сопоставьте формулы А, Б, В с графиками 1, 2, 3."
        )
        return hints[0], direction
    return hints


def _generate_candidate(
    family_id: str,
    seed: int,
    generator_version: str,
    retry_seed: int,
) -> Oge11Problem:
    if family_id not in FAMILIES:
        raise ValueError(f"Unknown task-11 family: {family_id}")
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported generator version: {generator_version}")
    rng = random.Random(f"{family_id}|{seed}|{retry_seed}|{generator_version}")
    sign_pairs = (
        cast(
            tuple[tuple[int, int], ...],
            tuple(rng.sample(((-1, -1), (-1, 1), (1, -1), (1, 1)), 3)),
        )
        if family_id in {"OGE11-F03", "OGE11-F04"}
        else None
    )
    generated: list[Graph] = []
    for index in range(3):
        for _ in range(96):
            candidate = _random_graph(family_id, rng, index, sign_pairs)
            if candidate not in generated:
                generated.append(candidate)
                break
        else:
            raise ValueError("bounded generation exhausted for task-11 family")
    graphs = (generated[0], generated[1], generated[2])
    _validate_graphs(graphs)
    formula_order = list(range(3))
    graph_order = list(range(3))
    rng.shuffle(formula_order)
    rng.shuffle(graph_order)
    orientation = (
        rng.choice(("formula_letters", "formula_options"))
        if family_id == "OGE11-F06"
        else None
    )
    condition, answer_kind, options = _format_condition(
        family_id, graphs, cast(tuple[int, int, int], tuple(formula_order)), orientation
    )
    graph_side_ids = cast(tuple[int, int, int], tuple(graph_order))
    if family_id == "OGE11-F04":
        # Letters identify coefficient-sign rows; digits identify graph panels.
        letter_graph_ids = cast(tuple[int, int, int], tuple(formula_order))
        digit_graph_ids = graph_side_ids
        mappings = [digit_graph_ids.index(graph_index) + 1 for graph_index in letter_graph_ids]
    elif answer_kind == "formula_options":
        # Graph letters identify graph order; answer digit points at formula order.
        letter_graph_ids = graph_side_ids
        digit_graph_ids = cast(tuple[int, int, int], tuple(formula_order))
        mappings = [digit_graph_ids.index(graph_index) + 1 for graph_index in letter_graph_ids]
    elif family_id == "OGE11-F03":
        letter_graph_ids = graph_side_ids
        digit_graph_ids = cast(tuple[int, int, int], tuple(formula_order))
        mappings = [digit_graph_ids.index(graph_index) + 1 for graph_index in letter_graph_ids]
    else:
        letter_graph_ids = cast(tuple[int, int, int], tuple(formula_order))
        digit_graph_ids = graph_side_ids
        mappings = [digit_graph_ids.index(graph_index) + 1 for graph_index in letter_graph_ids]
    code = "".join(str(item) for item in mappings)
    graph_labels = (
        ("А", "Б", "В")
        if family_id in {"OGE11-F02", "OGE11-F03", "OGE11-F07"}
        or (family_id == "OGE11-F06" and answer_kind == "formula_options")
        else ("1", "2", "3")
    )
    viewport = (Fraction(-5), Fraction(5), Fraction(-5), Fraction(5))
    png, render_audit = render_graphs(
        graphs, graph_side_ids, family_id, RENDERER_VERSION, viewport, graph_labels
    )
    image_hash = hashlib.sha256(png).hexdigest()
    problem_id = str(uuid5(NAMESPACE_URL, f"oge11:{family_id}:{seed}:{generator_version}"))
    solution = _build_solution(family_id, graphs, letter_graph_ids, digit_graph_ids, answer_kind)
    fingerprint = _semantic_fingerprint(
        family_id, graphs, letter_graph_ids, digit_graph_ids, condition, image_hash, viewport
    )
    return Oge11Problem(
        problem_id,
        seed,
        family_id,
        generator_version,
        RENDERER_VERSION,
        condition,
        graphs,
        graph_side_ids,
        graph_labels,
        letter_graph_ids,
        digit_graph_ids,
        answer_kind,
        options,
        code,
        _expected_hints(family_id, answer_kind),
        solution,
        png,
        image_hash,
        viewport,
        fingerprint,
    )


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Oge11Problem:
    """Generate a deterministic candidate and fail closed after bounded visual rejection."""
    last_reason = "unknown rejection"
    for retry_seed in range(64):
        problem = _generate_candidate(family_id, seed, generator_version, retry_seed)
        valid, last_reason = verify(problem)
        if valid:
            return replace(problem, generation_attempts=retry_seed + 1)
    raise RuntimeError(f"bounded generation exhausted for {family_id}: {last_reason}")


def from_snapshot(value: dict[str, object], *, audit_raster: bool = True) -> Oge11Problem:
    """Restore a saved task without rerunning generation or rendering.

    Skip the raster pass only when the same PNG was audited during issuance.
    The image digest and semantic fingerprint are always checked.
    """
    try:
        raw_graphs = value["graphs"]
        if not isinstance(raw_graphs, list) or len(raw_graphs) != 3:
            raise ValueError("snapshot must contain three graph models")
        graphs = cast(
            tuple[Graph, Graph, Graph],
            tuple(
                Graph(
                    str(item["kind"]),
                    tuple(Fraction(str(coefficient)) for coefficient in item["coefficients"]),
                )
                for item in raw_graphs
                if isinstance(item, dict)
            ),
        )
        if len(graphs) != 3:
            raise ValueError("invalid graph model")
        viewport_value = value["viewport"]
        if not isinstance(viewport_value, list) or len(viewport_value) != 4:
            raise ValueError("invalid viewport")

        def int_tuple(name: str) -> tuple[int, int, int]:
            raw = value[name]
            if (
                not isinstance(raw, list)
                or len(raw) != 3
                or any(not isinstance(item, int | str) for item in raw)
            ):
                raise ValueError(f"invalid {name}")
            return cast(tuple[int, int, int], tuple(int(item) for item in raw))

        def string_tuple(name: str) -> tuple[str, ...]:
            raw = value[name]
            if not isinstance(raw, list):
                raise ValueError(f"invalid {name}")
            return tuple(str(item) for item in raw)

        raw_seed = value["seed"]
        if not isinstance(raw_seed, int | str):
            raise ValueError("invalid seed")
        raw_attempts = value.get("generation_attempts", 1)
        if not isinstance(raw_attempts, int | str):
            raise ValueError("invalid generation attempts")
        png_value = value["png_base64"]
        raw_png = base64.b64decode(str(png_value), validate=True)
        result = Oge11Problem(
            problem_id=str(value["problem_id"]),
            seed=int(raw_seed),
            family_id=str(value["family_id"]),
            generator_version=str(value["generator_version"]),
            renderer_version=str(value["renderer_version"]),
            condition=str(value["condition"]),
            graphs=graphs,
            graph_order=int_tuple("graph_order"),
            graph_labels=cast(tuple[str, str, str], string_tuple("graph_labels")),
            letter_graph_ids=int_tuple("letter_graph_ids"),
            digit_graph_ids=int_tuple("digit_graph_ids"),
            answer_kind=str(value["answer_kind"]),
            options=cast(tuple[str, str, str], string_tuple("options")),
            correct_answer=str(value["correct_answer"]),
            hints=cast(tuple[str, str], string_tuple("hints")),
            solution=string_tuple("solution"),
            png_bytes=raw_png,
            image_sha256=str(value["image_sha256"]),
            viewport=cast(
                tuple[Fraction, Fraction, Fraction, Fraction],
                tuple(Fraction(str(item)) for item in viewport_value),
            ),
            fingerprint=str(value["fingerprint"]),
            generation_attempts=int(raw_attempts),
        )
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ValueError("invalid task-11 immutable snapshot") from error
    if (
        value.get("answer_policy_id") != POLICY_ID
        or value.get("answer_policy_version") != POLICY_VERSION
    ):
        raise ValueError("unsupported task-11 answer policy snapshot")
    valid, reason = verify(result, audit_raster=audit_raster)
    if not valid:
        raise ValueError(f"invalid task-11 snapshot: {reason}")
    return result


def _build_solution(
    family: str,
    graphs: tuple[Graph, Graph, Graph],
    letters: tuple[int, int, int],
    digits: tuple[int, int, int],
    answer_kind: str,
) -> tuple[str, ...]:
    steps: list[str] = []
    for letter, graph_index in zip(_LETTERS, letters, strict=True):
        graph = graphs[graph_index]
        if family == "OGE11-F03":
            k, b = graph.coefficients
            option = digits.index(graph_index) + 1
            step = (
                f"{letter}: k={'+' if k > 0 else '−'} по направлению прямой, "
                f"b={'+' if b > 0 else '−'} по y(0); это вариант {option}."
            )
        elif family == "OGE11-F04":
            a, _, c = graph.coefficients
            panel = digits.index(graph_index) + 1
            step = (
                f"{letter}: a {'>' if a > 0 else '<'} 0 по ветвям, "
                f"c {'>' if c > 0 else '<'} 0 по y(0); это график {panel}."
            )
        elif answer_kind == "formula_options":
            option = digits.index(graph_index) + 1
            step = (
                f"{letter}: график {graph.kind} подтверждает формулу "
                f"{option}) {graph.formula()}."
            )
        else:
            panel = digits.index(graph_index) + 1
            step = (
                f"{letter}) {graph.formula()} задаёт график {panel}; "
                f"контрольные значения соответствуют виду {graph.kind}."
            )
        steps.append(step)
    steps.append("Запишите номера соответствующих объектов в порядке А, Б, В.")
    return tuple(steps)


def _semantic_fingerprint(
    family_id: str,
    graphs: tuple[Graph, Graph, Graph],
    letters: tuple[int, int, int],
    digits: tuple[int, int, int],
    condition: str,
    image_sha256: str,
    viewport: tuple[Fraction, Fraction, Fraction, Fraction],
) -> str:
    payload = {
        "family": family_id,
        "graphs": [graph.as_json() for graph in graphs],
        "letter_graph_ids": letters,
        "digit_graph_ids": digits,
        "condition": condition,
        "image_sha256": image_sha256,
        "viewport": [_fraction_text(value) for value in viewport],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _audit_solution(problem: Oge11Problem) -> bool:
    """Check each written step from the graph models without using the builder."""
    if len(problem.solution) != 4:
        return False
    expected_steps: list[str] = []
    for letter, graph_id in zip(_LETTERS, problem.letter_graph_ids, strict=True):
        graph = problem.graphs[graph_id]
        if problem.family_id == "OGE11-F03":
            k, b = graph.coefficients
            option = problem.digit_graph_ids.index(graph_id) + 1
            expected_steps.append(
                f"{letter}: k={'+' if k > 0 else '−'} по направлению прямой, "
                f"b={'+' if b > 0 else '−'} по y(0); это вариант {option}."
            )
        elif problem.family_id == "OGE11-F04":
            a, _, c = graph.coefficients
            panel = problem.digit_graph_ids.index(graph_id) + 1
            expected_steps.append(
                f"{letter}: a {'>' if a > 0 else '<'} 0 по ветвям, "
                f"c {'>' if c > 0 else '<'} 0 по y(0); это график {panel}."
            )
        elif problem.answer_kind == "formula_options":
            option = problem.digit_graph_ids.index(graph_id) + 1
            expected_steps.append(
                f"{letter}: график {graph.kind} подтверждает формулу "
                f"{option}) {graph.formula()}."
            )
        else:
            panel = problem.digit_graph_ids.index(graph_id) + 1
            expected_steps.append(
                f"{letter}) {graph.formula()} задаёт график {panel}; "
                f"контрольные значения соответствуют виду {graph.kind}."
            )
    expected_steps.append("Запишите номера соответствующих объектов в порядке А, Б, В.")
    return tuple(expected_steps) == problem.solution


def verify(problem: Oge11Problem, *, audit_raster: bool = True) -> tuple[bool, str]:
    """Independent semantic and raster audit; returns a stable failure category."""
    if problem.family_id not in FAMILIES:
        return False, "unknown family"
    if problem.generator_version != GENERATOR_VERSION:
        return False, "unsupported generator version"
    if problem.renderer_version != RENDERER_VERSION:
        return False, "unsupported renderer version"
    if hashlib.sha256(problem.png_bytes).hexdigest() != problem.image_sha256:
        return False, "snapshot integrity violation"
    if re.fullmatch(r"[123]{3}", problem.correct_answer) is None or set(
        problem.correct_answer
    ) != set("123"):
        return False, "invalid answer code"
    try:
        expected_kind, expected_header = _VISIBLE_TASK_CONTRACTS[problem.family_id]
        if problem.family_id == "OGE11-F06":
            expected_kind = problem.answer_kind
            expected_header = (
                "Соотнесите графики А, Б, В с формулами из списка 1, 2, 3:"
                if problem.answer_kind == "formula_options"
                else "Соотнесите формулы А, Б, В с графиками 1, 2, 3:"
            )
        expected_graph_labels = (
            ("А", "Б", "В")
            if problem.family_id in {"OGE11-F02", "OGE11-F03", "OGE11-F07"}
            or (problem.family_id == "OGE11-F06" and problem.answer_kind == "formula_options")
            else ("1", "2", "3")
        )
        condition_lines = problem.condition.splitlines()
        if (
            problem.answer_kind != expected_kind
            or not condition_lines
            or condition_lines[0] != expected_header
            or problem.graph_labels != expected_graph_labels
        ):
            return False, "visible task structure differs from family contract"
        if problem.hints != _expected_hints(problem.family_id, problem.answer_kind):
            return False, "hints do not match family model"
        _validate_graphs(problem.graphs)
        if (
            len(problem.letter_graph_ids) != 3
            or set(problem.letter_graph_ids) != {0, 1, 2}
            or len(problem.digit_graph_ids) != 3
            or set(problem.digit_graph_ids) != {0, 1, 2}
            or len(problem.options) != 3
            or len(set(problem.options)) != 3
        ):
            return False, "matching sides are ambiguous or incomplete"
        if problem.graph_labels == ("А", "Б", "В"):
            if problem.letter_graph_ids != problem.graph_order:
                return False, "letter labels do not identify visible graph panels"
        elif problem.digit_graph_ids != problem.graph_order:
            return False, "digit labels do not identify visible graph panels"
        if problem.answer_kind == "formula_letters":
            visible = re.findall(r"[АБВ]\)\s*(y=[^\n]+)", problem.condition)
            parsed = tuple(_parse_formula(item) for item in visible)
            if len(parsed) != 3 or parsed != tuple(
                problem.graphs[i] for i in problem.letter_graph_ids
            ):
                return False, "visible formula differs from model"
            if (
                tuple(item[1] for item in re.findall(r"([АБВ])\)\s*(y=[^\n]+)", problem.condition))
                != problem.options
            ):
                return False, "visible formula options differ from stored options"
        elif problem.answer_kind == "formula_options":
            visible = re.findall(r"\d\)\s*(y=[^\n]+)", problem.condition)
            parsed = tuple(_parse_formula(item) for item in visible)
            if len(parsed) != 3 or parsed != tuple(
                problem.graphs[i] for i in problem.digit_graph_ids
            ):
                return False, "visible formula differs from model"
            if tuple(parsed_formula.formula() for parsed_formula in parsed) != problem.options:
                return False, "visible formula options differ from stored options"
        elif problem.answer_kind == "signs":
            visible = re.findall(r"\d\)\s*([ka]) ([+−-]), ([bc]) ([+−-])", problem.condition)
            if len(visible) != 3:
                return False, "visible sign options are malformed"
            expected_signs: list[tuple[str, ...]] = []
            for graph_id in problem.digit_graph_ids:
                graph = problem.graphs[graph_id]
                if problem.family_id == "OGE11-F03":
                    k, b = graph.coefficients
                    expected_signs.append(("k", "+" if k > 0 else "−", "b", "+" if b > 0 else "−"))
                else:
                    a, _, c = graph.coefficients
                    expected_signs.append(("a", "+" if a > 0 else "−", "c", "+" if c > 0 else "−"))
            normalized = [
                (left, sign_left.replace("-", "−"), right, sign_right.replace("-", "−"))
                for left, sign_left, right, sign_right in visible
            ]
            if normalized != expected_signs:
                return False, "visible sign options differ from model"
            if (
                tuple(
                    f"{left} {sign_left}, {right} {sign_right}"
                    for left, sign_left, right, sign_right in normalized
                )
                != problem.options
            ):
                return False, "visible sign options differ from stored options"
        elif problem.answer_kind == "signs_letters":
            visible = re.findall(r"[АБВ]\)\s*a ([<>]) 0, c ([<>]) 0", problem.condition)
            if len(visible) != 3:
                return False, "visible coefficient-sign rows are malformed"
            expected_signs = []
            for graph_id in problem.letter_graph_ids:
                a, _, c = problem.graphs[graph_id].coefficients
                expected_signs.append((">" if a > 0 else "<", ">" if c > 0 else "<"))
            if visible != expected_signs:
                return False, "visible coefficient-sign rows differ from graph models"
            if tuple(f"a {a} 0, c {c} 0" for a, c in visible) != problem.options:
                return False, "visible coefficient-sign rows differ from stored options"
        expected = "".join(
            str(problem.digit_graph_ids.index(graph_id) + 1)
            for graph_id in problem.letter_graph_ids
        )
        if expected != problem.correct_answer:
            return False, "wrong matching code"
        if not _audit_solution(problem):
            return False, "invalid reasoning step"
        if audit_raster:
            from app.math.oge11_render import audit_png

            audit_png(
                problem.png_bytes,
                problem.graphs,
                problem.graph_order,
                problem.viewport,
                problem.family_id,
                problem.graph_labels,
            )
        if problem.fingerprint != _semantic_fingerprint(
            problem.family_id,
            problem.graphs,
            problem.letter_graph_ids,
            problem.digit_graph_ids,
            problem.condition,
            problem.image_sha256,
            problem.viewport,
        ):
            return False, "semantic fingerprint mismatch"
    except (ValueError, OSError, IndexError, ZeroDivisionError):
        return False, "graph or formula audit failed"
    return True, "ok"


def parse_answer(value: str) -> str | None:
    """Parse only one exact ASCII permutation; preserve the code as a string."""
    if re.fullmatch(r"[123]{3}", value) is None or set(value) != set("123"):
        return None
    return value


def all_matching_codes() -> set[str]:
    return {"".join(p) for p in permutations("123")}
