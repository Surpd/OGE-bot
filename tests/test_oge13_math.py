from __future__ import annotations

import re
import struct
from dataclasses import replace
from fractions import Fraction

import pytest

from app.math.inequalities import (
    ENABLED_FAMILIES,
    FAMILIES,
    Interval,
    generate,
    independent_solve,
    render_option_sheet_png,
    validate,
)


def _condition_truth(condition: str, family: str, x: Fraction) -> bool:
    """Test-only evaluator: evaluates the printed inequality directly, not its solver result."""
    if family.startswith("OGE13-L"):
        match = re.fullmatch(
            r"(-?(?:\d+)?)x ([+-]) (\d+) ([<>]=?) (-?(?:\d+)?)x ([+-]) (\d+)", condition
        )
        assert match
        a, sa, b, rel, c, sc, d = match.groups()
        a = Fraction(-1 if a == "-" else 1 if a == "" else int(a))
        c = Fraction(-1 if c == "-" else 1 if c == "" else int(c))
        left = a * x + (int(b) if sa == "+" else -int(b))
        right = c * x + (int(d) if sc == "+" else -int(d))
    elif family.endswith("Q01"):
        match = re.fullmatch(r"x² - (\d+(?:,\d{1,2})?)x ([<>]=?) 0", condition)
        assert match
        k = Fraction(match.group(1).replace(",", "."))
        left = x * x - k * x
        right = 0
        rel = match.group(2)
    elif family.endswith("Q02"):
        match = re.fullmatch(r"x² \+ (\d+(?:,\d{1,2})?)x ([<>]=?) 0", condition)
        assert match
        k = Fraction(match.group(1).replace(",", "."))
        left = x * x + k * x
        right = 0
        rel = match.group(2)
    elif family.endswith("Q03"):
        match = re.fullmatch(r"-x² - (\d+(?:,\d{1,2})?)x ([<>]=?) 0", condition)
        assert match
        k = Fraction(match.group(1).replace(",", "."))
        left = -x * x - k * x
        right = 0
        rel = match.group(2)
    elif family.endswith("Q04"):
        match = re.fullmatch(
            r"\(x ([+-]) (\d+(?:,\d{1,2})?)\)\(x ([+-]) (\d+(?:,\d{1,2})?)\) ([<>]=?) 0", condition
        )
        assert match
        s1, n1, s2, n2, rel = match.groups()
        left = (
            x + (Fraction(n1.replace(",", ".")) if s1 == "+" else -Fraction(n1.replace(",", ".")))
        ) * (x + (Fraction(n2.replace(",", ".")) if s2 == "+" else -Fraction(n2.replace(",", "."))))
        right = 0
    else:
        rows = condition.splitlines()
        assert len(rows) == 2
        for row in rows:
            match = re.fullmatch(r"x ([<>]=?) (-?\d+(?:,\d{1,2})?)", row)
            assert match
            rel, raw = match.groups()
            bound = Fraction(raw.replace(",", "."))
            if not _compare(x, bound, rel):
                return False
        return True
    return _compare(left, right, rel)


def _compare(left: Fraction, right: Fraction, relation: str) -> bool:
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[relation]


def _contains(option, x: Fraction) -> bool:
    for item in option:
        left_ok = item.left is None or x > item.left or (x == item.left and item.left_closed)
        right_ok = item.right is None or x < item.right or (x == item.right and item.right_closed)
        if left_ok and right_ok:
            return True
    return False


def _probe_points() -> tuple[Fraction, ...]:
    # Conditions use at most two decimal places, so the grid includes exact boundaries.
    return tuple(Fraction(i, 100) for i in range(-1200, 1201))


def _oracle_matching_options(problem, condition: str | None = None) -> list[int]:
    condition = problem.condition if condition is None else condition
    probes = _critical_probe_points(condition, problem.family_id, problem.options)
    return [
        number
        for number, option in enumerate(problem.options, 1)
        if all(
            _contains(option, x) == _condition_truth(condition, problem.family_id, x)
            for x in probes
        )
    ]


def _critical_probe_points(condition: str, family: str, options=()) -> tuple[Fraction, ...]:
    """Probe each polynomial sign region and every exact boundary point."""
    boundaries: set[Fraction] = set()
    if family.startswith("OGE13-L"):
        match = re.fullmatch(
            r"(-?(?:\d+)?)x ([+-]) (\d+) ([<>]=?) (-?(?:\d+)?)x ([+-]) (\d+)",
            condition,
        )
        assert match
        a, sign_a, b, _, c, sign_c, d = match.groups()
        coefficient_a = -1 if a == "-" else 1 if a == "" else int(a)
        coefficient_c = -1 if c == "-" else 1 if c == "" else int(c)
        constant_a = int(b) if sign_a == "+" else -int(b)
        constant_c = int(d) if sign_c == "+" else -int(d)
        boundaries.add(Fraction(constant_c - constant_a, coefficient_a - coefficient_c))
    elif family.endswith(("Q01", "Q02", "Q03")):
        match = re.search(r"(\d+(?:,\d{1,2})?)x", condition)
        assert match
        root = Fraction(match.group(1).replace(",", "."))
        boundaries.add(Fraction(0))
        boundaries.add(root if family.endswith("Q01") else -root)
    elif family.endswith("Q04"):
        match = re.fullmatch(
            r"\(x ([+-]) (\d+(?:,\d{1,2})?)\)"
            r"\(x ([+-]) (\d+(?:,\d{1,2})?)\) ([<>]=?) 0",
            condition,
        )
        assert match
        sign_a, value_a, sign_b, value_b, _ = match.groups()
        boundaries.update(
            (
                Fraction(value_a.replace(",", ".")) * (-1 if sign_a == "+" else 1),
                Fraction(value_b.replace(",", ".")) * (-1 if sign_b == "+" else 1),
            )
        )
    else:
        for row in condition.splitlines():
            match = re.fullmatch(r"x ([<>]=?) (-?\d+(?:,\d{1,2})?)", row)
            assert match
            boundaries.add(Fraction(match.group(2).replace(",", ".")))

    for option in options:
        for interval in option:
            if interval.left is not None:
                boundaries.add(interval.left)
            if interval.right is not None:
                boundaries.add(interval.right)
    ordered = sorted(boundaries)
    if not ordered:
        return (Fraction(-1), Fraction(0), Fraction(1))
    probes = {ordered[0] - 1, ordered[-1] + 1, *ordered}
    probes.update((left + right) / 2 for left, right in zip(ordered, ordered[1:], strict=False))
    return tuple(sorted(probes))


def test_all_pilot_families_are_deterministic_disabled_and_audited() -> None:
    assert ENABLED_FAMILIES == ()
    for family in FAMILIES:
        first = generate(family, 24013)
        second = generate(family, 24013)
        assert first == second
        assert validate(first)
        assert len(first.options) == 4
        assert len(set(first.options)) == 4
        assert first.options[first.correct_option_number - 1] == first.solution_set
        assert _oracle_matching_options(first) == [first.correct_option_number]
        assert first.condition_audit
        assert first.to_snapshot()["correct_answer"] == str(first.correct_option_number)


@pytest.mark.parametrize(
    ("condition", "family", "expected"),
    [
        ("-2x + 1 < 0x + 3", "OGE13-L01", (Interval(Fraction(-1), None),)),
        ("x² - 4x < 0", "OGE13-Q01", (Interval(Fraction(0), Fraction(4)),)),
        (
            "x² + 5x >= 0",
            "OGE13-Q02",
            (Interval(None, Fraction(-5), False, True), Interval(Fraction(0), None, True, False)),
        ),
        (
            "-x² - 5x <= 0",
            "OGE13-Q03",
            (Interval(None, Fraction(-5), False, True), Interval(Fraction(0), None, True, False)),
        ),
        ("x >= -2\nx <= 4", "OGE13-S01", (Interval(Fraction(-2), Fraction(4), True, True),)),
        ("x > 2\nx < 2", "OGE13-S03", ()),
        ("x² - 1,25x < 0", "OGE13-Q01", (Interval(Fraction(0), Fraction(5, 4)),)),
        (
            "x² + 1,25x >= 0",
            "OGE13-Q02",
            (
                Interval(None, Fraction(-5, 4), False, True),
                Interval(Fraction(0), None, True, False),
            ),
        ),
        (
            "-x² - 1,25x <= 0",
            "OGE13-Q03",
            (
                Interval(None, Fraction(-5, 4), False, True),
                Interval(Fraction(0), None, True, False),
            ),
        ),
        (
            "(x + 1,5)(x - 2,5) > 0",
            "OGE13-Q04",
            (Interval(None, Fraction(-3, 2)), Interval(Fraction(5, 2), None)),
        ),
        (
            "x >= -1,5\nx <= 2,5",
            "OGE13-S01",
            (Interval(Fraction(-3, 2), Fraction(5, 2), True, True),),
        ),
    ],
)
def test_independent_solver_boundary_and_sign_cases(condition, family, expected) -> None:
    assert independent_solve(condition, family) == expected


def test_empty_set_model_and_svg_png_are_available() -> None:
    problem = generate("OGE13-S03", 6)
    assert independent_solve("x > 2\nx < 2", "OGE13-S03") == ()
    # A seed producing a valid system always yields four distinct mathematical options.
    png = render_option_sheet_png(problem)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (1280, 1120)
    assert all(svg.startswith("<svg") for svg in problem.option_svgs)


def test_answer_parser_accepts_option_number_or_exact_text() -> None:
    problem = generate("OGE13-L02", 77)
    assert problem.accepts(str(problem.correct_option_number))
    assert problem.accepts(problem.option_texts[problem.correct_option_number - 1])
    assert not problem.accepts("0")


def test_condition_audit_rejects_changed_visible_condition() -> None:
    problem = generate("OGE13-L01", 9)
    assert independent_solve(problem.condition, problem.family_id) == problem.solution_set
    with pytest.raises(ValueError):
        independent_solve(problem.condition + "x", problem.family_id)


@pytest.mark.parametrize("family", FAMILIES)
def test_independent_pointwise_oracle_finds_exactly_one_option_after_shuffle(family: str) -> None:
    problem = generate(family, 829)
    matches = _oracle_matching_options(problem)
    assert matches == [problem.correct_option_number]


def test_condition_mutations_change_solver_and_fail_validation() -> None:
    problem = generate("OGE13-Q01", 19)
    changed = replace(problem, condition=problem.condition.replace("<", ">"))
    assert _oracle_matching_options(problem, changed.condition) == []
    assert not validate(changed)

    linear = generate("OGE13-L02", 57)
    relation = re.search(r"(<=|>=|<|>)", linear.condition)
    assert relation
    flipped = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}[relation.group()]
    mutated_text = (
        linear.condition[: relation.start()] + flipped + linear.condition[relation.end() :]
    )
    assert _oracle_matching_options(linear, mutated_text) == []
    assert not validate(replace(linear, condition=mutated_text))


def test_endpoint_openness_direction_and_answer_mapping_mutations_fail() -> None:
    problem = generate("OGE13-L02", 102)
    correct = problem.options[problem.correct_option_number - 1]
    segment = correct[0]
    mutated_segment = (
        replace(segment, left_closed=not segment.left_closed)
        if segment.left is not None
        else replace(segment, right_closed=not segment.right_closed)
    )
    options = list(problem.options)
    options[problem.correct_option_number - 1] = (mutated_segment,)
    assert not validate(replace(problem, options=tuple(options)))

    reversed_segment = replace(
        segment,
        left=segment.right,
        right=segment.left,
        left_closed=segment.right_closed,
        right_closed=segment.left_closed,
    )
    options = list(problem.options)
    options[problem.correct_option_number - 1] = (reversed_segment,)
    assert not validate(replace(problem, options=tuple(options)))

    assert not validate(replace(problem, correct_answer=str(problem.correct_option_number % 4 + 1)))
    wrong_number = problem.correct_option_number % 4 + 1
    assert not validate(replace(problem, correct_option_number=wrong_number))


def test_svg_is_bound_to_ordered_options_and_png_rows_follow_option_order() -> None:
    problem = generate("OGE13-S01", 129)
    assert validate(problem)
    changed_svgs = list(problem.option_svgs)
    changed_svgs[0], changed_svgs[1] = changed_svgs[1], changed_svgs[0]
    assert not validate(replace(problem, option_svgs=tuple(changed_svgs)))

    changed_options = list(problem.options)
    changed_options[0], changed_options[1] = changed_options[1], changed_options[0]
    reordered = replace(problem, options=tuple(changed_options))
    assert render_option_sheet_png(problem) != render_option_sheet_png(reordered)


@pytest.mark.parametrize("family", FAMILIES)
def test_250_unique_conditions_within_1200_attempts(family: str) -> None:
    conditions: dict[str, object] = {}
    attempts = 0
    for seed in range(1200):
        attempts = seed + 1
        problem = generate(family, seed)
        conditions[problem.condition] = problem
        if len(conditions) >= 250:
            break
    assert len(conditions) >= 250
    assert attempts <= 1200
    assert all(
        _oracle_matching_options(problem) == [problem.correct_option_number]
        for problem in conditions.values()
    )


@pytest.mark.parametrize("family", FAMILIES)
def test_fast_40_condition_option_oracles(family: str) -> None:
    for seed in range(40):
        problem = generate(family, seed)
        assert _oracle_matching_options(problem) == [problem.correct_option_number]
