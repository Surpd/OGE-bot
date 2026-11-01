from __future__ import annotations

import random
import re
import struct
import zlib
from dataclasses import replace
from fractions import Fraction

import pytest

from app.math.inequalities import (
    ENABLED_FAMILIES,
    FAMILIES,
    Interval,
    _svg,
    generate,
    independent_solve,
    render_option_sheet_png,
    render_option_sheet_snapshot_png,
    format_set,
    _solution_steps,
    validate,
    validate_snapshot,
)


def _test_linear_expression(expression: str) -> tuple[Fraction, Fraction]:
    compact = expression.replace(" ", "")
    terms = re.findall(r"[+-]?[^+-]+", compact)
    assert "".join(terms) == compact
    coefficient = Fraction(0)
    constant = Fraction(0)
    for term in terms:
        if term.endswith("x"):
            raw = term[:-1]
            coefficient += Fraction(-1 if raw == "-" else 1 if raw in ("", "+") else raw)
        else:
            constant += Fraction(term.replace(",", "."))
    return coefficient, constant


def _test_comparison(row: str, x: Fraction) -> bool:
    matches = list(re.finditer(r"<=|>=|<|>", row))
    assert len(matches) == 1
    match = matches[0]
    left = _test_linear_expression(row[: match.start()])
    right = _test_linear_expression(row[match.end() :])
    left_value, right_value = left[0] * x + left[1], right[0] * x + right[1]
    return _compare(left_value, right_value, match.group())


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
        return all(_test_comparison(row, x) for row in rows)
    return _compare(left, right, rel)


def _compare(left: Fraction, right: Fraction, relation: str) -> bool:
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[relation]


def _test_display(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    scaled = value.numerator * 100 // value.denominator
    whole, remainder = divmod(abs(scaled), 100)
    decimals = f"{remainder:02d}".rstrip("0")
    return f"{'-' if scaled < 0 else ''}{whole},{decimals}"


def _test_quadratic_value(condition: str, family: str, x: Fraction) -> Fraction:
    number = r"\d+(?:,\d{1,2})?"
    if family.endswith("Q01"):
        match = re.fullmatch(rf"x² - ({number})x (<) 0", condition)
        assert match
        return x * x - Fraction(match.group(1).replace(",", ".")) * x
    if family.endswith("Q02"):
        match = re.fullmatch(rf"x² \+ ({number})x (>=) 0", condition)
        assert match
        return x * x + Fraction(match.group(1).replace(",", ".")) * x
    if family.endswith("Q03"):
        match = re.fullmatch(rf"-x² - ({number})x (<=) 0", condition)
        assert match
        return -(x * x) - Fraction(match.group(1).replace(",", ".")) * x
    match = re.fullmatch(
        rf"(-?)\(x ([+-]) ({number})\)\(x ([+-]) ({number})\) ([<>]=?) 0",
        condition,
    )
    assert match
    leading, op_a, raw_a, op_b, raw_b, _ = match.groups()
    factor_a = x + (1 if op_a == "+" else -1) * Fraction(raw_a.replace(",", "."))
    factor_b = x + (1 if op_b == "+" else -1) * Fraction(raw_b.replace(",", "."))
    return (-1 if leading else 1) * factor_a * factor_b


def _expected_explanation(condition: str, family: str) -> tuple[str, ...]:
    if family.startswith("OGE13-L"):
        relation_match = re.search(r"<=|>=|<|>", condition)
        assert relation_match
        relation = relation_match.group()
        lhs = _test_linear_expression(condition[: relation_match.start()])
        rhs = _test_linear_expression(condition[relation_match.end() :])
        coefficient, constant = lhs[0] - rhs[0], lhs[1] - rhs[1]
        right_side = -constant
        assert coefficient
        coefficient_text = (
            "x"
            if coefficient == 1
            else "-x"
            if coefficient == -1
            else f"{_test_display(coefficient)}x"
        )
        divided_relation = relation
        sign_note = "знак сохраняется"
        if coefficient < 0:
            divided_relation = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[
                relation
            ]
            sign_note = "знак меняется"
        boundary = right_side / coefficient
        result = independent_solve(condition, family)
        return (
            f"Исходное неравенство: {condition}.",
            f"Переносим слагаемые: {coefficient_text} {relation} {_test_display(right_side)}.",
            f"Делим обе части на {_test_display(coefficient)} "
            f"({'<0' if coefficient < 0 else '>0'}), {sign_note}: "
            f"x {divided_relation} {_test_display(boundary)}.",
            "Ответ: " + format_set(result) + ".",
        )

    number = r"\d+(?:,\d{1,2})?"
    if family.endswith("Q01"):
        match = re.fullmatch(rf"x² - ({number})x (<) 0", condition)
        assert match
        roots = (Fraction(0), Fraction(match.group(1).replace(",", ".")))
        leading, relation = 1, match.group(2)
        factorization = (
            f"Раскладываем: x² - {_test_display(roots[1])}x "
            f"= x(x - {_test_display(roots[1])})"
        )
    elif family.endswith("Q02"):
        match = re.fullmatch(rf"x² \+ ({number})x (>=) 0", condition)
        assert match
        value = Fraction(match.group(1).replace(",", "."))
        roots, leading, relation = (-value, Fraction(0)), 1, match.group(2)
        factorization = (
            f"Раскладываем: x² + {_test_display(value)}x "
            f"= x(x + {_test_display(value)})"
        )
    elif family.endswith("Q03"):
        match = re.fullmatch(rf"-x² - ({number})x (<=) 0", condition)
        assert match
        value = Fraction(match.group(1).replace(",", "."))
        roots, leading, relation = (-value, Fraction(0)), -1, match.group(2)
        factorization = (
            f"Раскладываем: −x² − {_test_display(value)}x "
            f"= −x(x + {_test_display(value)})"
        )
    else:
        match = re.fullmatch(
            rf"(-?)\(x ([+-]) ({number})\)\(x ([+-]) ({number})\) ([<>]=?) 0",
            condition,
        )
        assert match
        sign_a, op_a, raw_a, op_b, raw_b, relation = match.groups()
        roots = tuple(
            sorted(
                (
                    Fraction(raw_a.replace(",", ".")) * (-1 if op_a == "+" else 1),
                    Fraction(raw_b.replace(",", ".")) * (-1 if op_b == "+" else 1),
                )
            )
        )
        leading = -1 if sign_a else 1
        relation_match = re.search(r"[<>]=? 0$", condition)
        assert relation_match
        factorization = (
            "Выражение уже разложено на множители: "
            + condition[: relation_match.start()].rstrip()
        )
    left_root, right_root = roots
    probes = (left_root - 1, (left_root + right_root) / 2, right_root + 1)
    signs = tuple(
        "+" if _test_quadratic_value(condition, family, point) > 0 else "−"
        for point in probes
    )
    strict = len(relation) == 1
    desired_sign = "+" if relation[0] == ">" else "−"
    if signs[0] == desired_sign:
        result = (
            Interval(None, left_root, False, not strict),
            Interval(right_root, None, not strict, False),
        )
    else:
        result = (Interval(left_root, right_root, not strict, not strict),)
    root_note = (
        "не включаем, так как неравенство строгое"
        if strict
        else "включаем, так как знак неравенства нестрогий"
    )
    return (
        f"{factorization}; корни: x = {_test_display(left_root)} "
        f"и x = {_test_display(right_root)}.",
        "Знаки выражения на промежутках: "
        f"(−∞;{_test_display(left_root)}): {signs[0]}; "
        f"({_test_display(left_root)};{_test_display(right_root)}): {signs[1]}; "
        f"({_test_display(right_root)};+∞): {signs[2]}.",
        f"Для условия {relation} 0 выбираем подходящие промежутки; корни {root_note}.",
        "Ответ: " + format_set(result) + ".",
    )


def _contains(option, x: Fraction) -> bool:
    for item in option:
        left_ok = item.left is None or x > item.left or (x == item.left and item.left_closed)
        right_ok = item.right is None or x < item.right or (x == item.right and item.right_closed)
        if left_ok and right_ok:
            return True
    return False


def _decode_rgb_png(image: bytes) -> tuple[int, int, bytes]:
    offset = 8
    compressed = bytearray()
    width = height = color_type = bit_depth = None
    while offset < len(image):
        size = struct.unpack(">I", image[offset : offset + 4])[0]
        kind = image[offset + 4 : offset + 8]
        data = image[offset + 8 : offset + 8 + size]
        offset += size + 12
        if kind == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])[:4]
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break
    assert width is not None and height is not None
    assert bit_depth == 8 and color_type == 2
    raw = zlib.decompress(compressed)
    stride = width * 3
    pixels = bytearray()
    for row in range(height):
        start = row * (stride + 1)
        assert raw[start] == 0
        pixels.extend(raw[start + 1 : start + 1 + stride])
    return width, height, bytes(pixels)


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
            match = re.search(r"<=|>=|<|>", row)
            assert match
            left = _test_linear_expression(row[: match.start()])
            right = _test_linear_expression(row[match.end() :])
            coefficient, constant = left[0] - right[0], left[1] - right[1]
            if coefficient:
                boundaries.add(-constant / coefficient)

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
        (
            "x + 2,6 <= 0\nx + 5 >= 1",
            "OGE13-S01",
            (Interval(Fraction(-4), Fraction(-13, 5), True, True),),
        ),
        (
            "x + 3 >= -2\nx + 1,1 >= 0",
            "OGE13-S02",
            (Interval(Fraction(-11, 10), None, True, False),),
        ),
        (
            "x > 3\n4 - x > 0",
            "OGE13-S03",
            (Interval(Fraction(3), Fraction(4)),),
        ),
        (
            "-2x + 1 <= 0\n3x - 4 <= -1",
            "OGE13-S01",
            (Interval(Fraction(1, 2), Fraction(1), True, True),),
        ),
    ],
)
def test_independent_solver_boundary_and_sign_cases(condition, family, expected) -> None:
    assert independent_solve(condition, family) == expected


@pytest.mark.parametrize(
    "family", ("OGE13-L01", "OGE13-L02", "OGE13-Q01", "OGE13-Q02", "OGE13-Q03", "OGE13-Q04")
)
def test_linear_and_quadratic_explanations_are_derived_and_independently_checked(
    family: str,
) -> None:
    for seed in range(30):
        problem = generate(family, seed)
        assert problem.solution == _expected_explanation(problem.condition, family)
        assert validate(problem)

        mutated = replace(problem, solution=problem.solution[:-1] + ("Ответ: 999.",))
        assert not validate(mutated)


def test_linear_explanation_reverses_comparison_when_divisor_is_negative() -> None:
    condition = "-2x + 1 < 0x + 3"
    solution = (Interval(Fraction(-1), None),)

    steps = _solution_steps(condition, "OGE13-L01", solution)

    assert steps == (
        "Исходное неравенство: -2x + 1 < 0x + 3.",
        "Переносим слагаемые: -2x < 2.",
        "Делим обе части на -2 (<0), знак меняется: x > -1.",
        "Ответ: (-1;+∞).",
    )


@pytest.mark.parametrize(
    ("condition", "family", "closed"),
    (
        ("x² - 4x < 0", "OGE13-Q01", False),
        ("x² + 4x >= 0", "OGE13-Q02", True),
        ("-x² - 4x <= 0", "OGE13-Q03", True),
        ("(x + 2)(x - 1) < 0", "OGE13-Q04", False),
        ("(x + 2)(x - 1) <= 0", "OGE13-Q04", True),
        ("(x + 2)(x - 1) >= 0", "OGE13-Q04", True),
    ),
)
def test_quadratic_explanations_show_sign_chart_and_boundary_inclusion(
    condition: str, family: str, closed: bool
) -> None:
    solution = independent_solve(condition, family)

    steps = _solution_steps(condition, family, solution)
    expected = _expected_explanation(condition, family)

    assert steps == expected
    assert "корни:" in steps[0]
    assert "Знаки выражения на промежутках" in steps[1]
    assert ("корни включаем" in steps[2]) is closed
    assert ("корни не включаем" in steps[2]) is not closed
    assert steps[-1].endswith(format_set(solution) + ".")


def test_empty_set_model_and_svg_png_are_available() -> None:
    problem = generate("OGE13-S03", 6)
    assert independent_solve("x > 2\nx < 2", "OGE13-S03") == ()
    # A seed producing a valid system always yields four distinct mathematical options.
    png = render_option_sheet_png(problem)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (1280, 1120)
    assert all(svg.startswith("<svg") for svg in problem.option_svgs)


def test_distractors_reject_reversed_and_noncanonical_intervals() -> None:
    from app.math.inequalities import _distractors, _is_canonical_interval_set

    correct = (Interval(Fraction(0), Fraction(1, 2)),)
    options = _distractors(correct, random.Random(13))

    assert len(options) == 4
    assert len(set(options)) == 4
    assert all(_is_canonical_interval_set(option) for option in options)
    assert not _is_canonical_interval_set((Interval(Fraction(1), Fraction(1, 2)),))
    assert (Interval(Fraction(1), Fraction(1, 2)),) not in options
    assert _is_canonical_interval_set((Interval(Fraction(2), Fraction(2), True, True),))
    assert not _is_canonical_interval_set((Interval(Fraction(2), Fraction(2)),))
    assert not _is_canonical_interval_set(
        (Interval(Fraction(0), Fraction(2)), Interval(Fraction(1), Fraction(3)))
    )
    assert not _is_canonical_interval_set(
        (Interval(Fraction(0), Fraction(1), True, True), Interval(Fraction(1), None))
    )


@pytest.mark.parametrize(
    "family", ("OGE13-L02", "OGE13-Q04", "OGE13-S01", "OGE13-S02", "OGE13-S03")
)
def test_png_pixels_match_each_saved_interval_and_boundary(family: str) -> None:
    problem = generate(family, 2701)
    width, height, pixels = _decode_rgb_png(render_option_sheet_png(problem))
    assert (width, height) == (1280, 1120)
    blue, ink, white = (23, 105, 170), (34, 34, 34), (255, 255, 255)

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        offset = (y * width + x) * 3
        return tuple(pixels[offset : offset + 3])

    for option_index, option in enumerate(problem.options):
        axis_y = 185 + option_index * 250
        endpoints = [
            endpoint
            for interval in option
            for endpoint in (interval.left, interval.right)
            if endpoint is not None
        ]
        for x in range(120, 1161, 7):
            if any(abs(x - (640 + tick * 36)) <= 2 for tick in range(-12, 13, 4)):
                continue
            if any(abs(x - round(640 + float(endpoint) * 36)) <= 14 for endpoint in endpoints):
                continue
            number = Fraction(x - 640, 36)
            expected = _contains(option, number)
            assert pixel(x, axis_y) == (blue if expected else ink)
        for interval in option:
            for endpoint, closed in (
                (interval.left, interval.left_closed),
                (interval.right, interval.right_closed),
            ):
                if endpoint is None:
                    continue
                center_x = round(640 + float(endpoint) * 36)
                assert pixel(center_x, axis_y) == (blue if closed else white)


def test_snapshot_renderer_uses_saved_options_and_rejects_unknown_versions() -> None:
    problem = generate("OGE13-Q04", 702)
    snapshot = problem.to_snapshot()
    assert validate_snapshot(snapshot)
    assert render_option_sheet_snapshot_png(snapshot) == render_option_sheet_png(problem)

    tampered = dict(snapshot)
    tampered["correct_option_number"] = problem.correct_option_number % 4 + 1
    assert not validate_snapshot(tampered)

    unsupported = dict(snapshot)
    unsupported["generator_version"] = "99.0.0"
    assert not validate_snapshot(unsupported)
    with pytest.raises(ValueError, match="Unsupported OGE13 generator version"):
        render_option_sheet_snapshot_png(unsupported)
    with pytest.raises(ValueError, match="Unsupported OGE13 generator version"):
        generate("OGE13-S01", 1, generator_version="99.0.0")


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


def test_original_system_source_cases_are_independently_solved() -> None:
    cases = (
        (
            "x + 2,6 <= 0\nx + 5 >= 1",
            "OGE13-S01",
            (Interval(Fraction(-4), Fraction(-13, 5), True, True),),
        ),
        (
            "x + 3 >= -2\nx + 1,1 >= 0",
            "OGE13-S02",
            (Interval(Fraction(-11, 10), None, True, False),),
        ),
        (
            "x > 3\n4 - x > 0",
            "OGE13-S03",
            (Interval(Fraction(3), Fraction(4)),),
        ),
    )
    for condition, family, expected in cases:
        assert independent_solve(condition, family) == expected
        probes = _critical_probe_points(condition, family, (expected,))
        assert all(
            _contains(expected, point) == _condition_truth(condition, family, point)
            for point in probes
        )


@pytest.mark.parametrize("family", ("OGE13-S01", "OGE13-S02", "OGE13-S03"))
def test_system_generators_keep_source_algebra_and_vary_coefficients(family: str) -> None:
    seen_coefficients: set[Fraction] = set()
    for seed in range(100):
        problem = generate(family, seed)
        rows = problem.condition.splitlines()
        assert len(rows) == 2
        assert all("x" in row and re.search(r"[<>]=?", row) for row in rows)
        assert not all(re.fullmatch(r"x [<>]=? -?\d+(?:,\d+)?", row) for row in rows)
        for row in rows:
            comparison = re.search(r"<=|>=|<|>", row)
            assert comparison
            coefficient = _test_linear_expression(row[: comparison.start()])[0]
            seen_coefficients.add(abs(coefficient))
        if family == "OGE13-S03":
            second_left = rows[1].split(">", maxsplit=1)[0]
            assert _test_linear_expression(second_left)[0] < 0
        assert validate(problem)
    assert len(seen_coefficients) >= 3


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

    order = (1, 0, 2, 3)
    reordered = replace(
        problem,
        options=tuple(problem.options[index] for index in order),
        option_texts=tuple(problem.option_texts[index] for index in order),
        option_svgs=tuple(
            _svg(problem.options[index], position + 1) for position, index in enumerate(order)
        ),
        display_order=tuple(problem.display_order[index] for index in order),
        correct_option_number=order.index(problem.correct_option_number - 1) + 1,
        correct_answer=str(order.index(problem.correct_option_number - 1) + 1),
    )
    assert validate(reordered)
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
