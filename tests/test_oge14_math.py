from __future__ import annotations

import re
from fractions import Fraction

import pytest

from app.math.progressions import (
    A04,
    A11,
    ALL_FAMILIES,
    ENABLED_FAMILIES,
    FAMILY_STATUS,
    SOURCE_IDS,
    _arithmetic_sum,
    _enumerate,
    _explanation,
    _model,
    _render,
    audit_condition,
    generate,
    solve_condition,
)

IMPLEMENTED = tuple(f for f in ALL_FAMILIES if f not in {A04, A11})


def test_task14_all_23_reference_cases_pass_independent_package_oracle() -> None:
    # The full source-case regression and archive reference oracle live in the
    # preserved research package and are run in CI as part of this suite.
    import subprocess
    import sys
    from pathlib import Path

    package = Path("specs/research/oge14_generator_v3")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-q", "test_oge14_reference_oracle.py"],
        cwd=package,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_task14_all_research_structures_have_source_ids_and_explicit_status() -> None:
    assert set(SOURCE_IDS) == set(ALL_FAMILIES)
    assert all(SOURCE_IDS[family] for family in ALL_FAMILIES)
    assert A04 not in ENABLED_FAMILIES and A11 not in ENABLED_FAMILIES
    assert set(ENABLED_FAMILIES) == {
        family for family in IMPLEMENTED if family != "OGE14-A06"
    }
    assert FAMILY_STATUS[A04] == "disabled_hold_historical_topic"
    assert FAMILY_STATUS[A11] == "disabled_hold_degenerate_progression"


@pytest.mark.parametrize("family", IMPLEMENTED)
def test_task14_generator_is_deterministic_and_oracles_agree(family: str) -> None:
    for seed in range(250):
        first = generate(family, seed)
        again = generate(family, seed)
        assert first == again
        assert audit_condition(family, first.condition, first.parameters)
        assert _enumerate(family, first.parameters) == first.exact_value
        assert solve_condition(family, first.condition) == first.exact_value
        assert first.correct_answer
        assert first.to_snapshot()["content_provenance"] == "generated_analogue"


@pytest.mark.parametrize("family", IMPLEMENTED)
def test_task14_visible_text_mutations_are_rejected(family: str) -> None:
    problem = generate(family, 2114)
    text = problem.condition
    assert not audit_condition(family, text + " ", problem.parameters)
    unit = next((unit for unit in (" °C", " мг", " см", " м") if unit in text), None)
    if unit is not None:
        mutated = text.replace(unit, " altered-unit", 1)
        assert not audit_condition(family, mutated, problem.parameters)
    numeric_tokens = list(re.finditer(r"(?<!\w)-?\d+(?:,\d+)?", text))
    assert numeric_tokens
    for token in numeric_tokens:
        visible = token.group().replace(",", ".")
        replacement = str(Fraction(visible) + 1).replace(".", ",")
        changed = text[: token.start()] + replacement + text[token.end() :]
        assert not audit_condition(family, changed, problem.parameters)


def test_task14_semantic_mutations_change_or_invalidate_independent_answer() -> None:
    cases = (
        ("OGE14-A05", "снижалась", "повышалась"),
        ("OGE14-A06", "до полной остановки", "за первые 5 секунд"),
        ("OGE14-A07", "за первые", "до полной остановки за первые"),
        ("OGE14-G03", "вещества Б", "вещества А"),
        ("OGE14-G04", "меньше", "не больше"),
    )
    for family, before, after in cases:
        problem = generate(family, 711)
        assert before in problem.condition
        mutated = problem.condition.replace(before, after)
        assert not audit_condition(family, mutated, problem.parameters)
        assert solve_condition(family, mutated) is None

    a10 = generate("OGE14-A10", 711)
    index = int(a10.parameters["k"])
    changed_index = index + 1 if index < int(a10.parameters["n"]) - 1 else index - 1
    changed_target = a10.condition.replace(f"{index}-й день", f"{changed_index}-й день")
    assert not audit_condition("OGE14-A10", changed_target, a10.parameters)
    assert solve_condition("OGE14-A10", changed_target) != a10.exact_value

    bounce = generate("OGE14-G04", 711)
    changed_indexing = bounce.condition.replace("первого отскока", "нулевого отскока")
    assert not audit_condition("OGE14-G04", changed_indexing, bounce.parameters)
    assert solve_condition("OGE14-G04", changed_indexing) is None


@pytest.mark.parametrize(
    ("family", "old_unit", "new_unit"),
    (
        ("OGE14-A05", "°C", "°F"),
        ("OGE14-A06", " м", " км"),
        ("OGE14-A07", " м", " км"),
        ("OGE14-A08", " м", " км"),
        ("OGE14-A09", " м", " см"),
        ("OGE14-G01", " мг", " г"),
        ("OGE14-G02", " мг", " г"),
        ("OGE14-G03", " мг", " г"),
        ("OGE14-G04", " см", " м"),
    ),
)
def test_task14_unit_mutations_fail_rendered_condition_audit(
    family: str, old_unit: str, new_unit: str
) -> None:
    problem = generate(family, 2114)
    assert old_unit in problem.condition
    changed = problem.condition.replace(old_unit, new_unit, 1)
    assert not audit_condition(family, changed, problem.parameters)


def test_task14_finite_stop_family_is_documented_as_bounded() -> None:
    fingerprints = {generate("OGE14-A06", seed).fingerprint for seed in range(1200)}
    assert len(fingerprints) == 42


def test_task14_russian_counted_nouns_and_sensitive_boundaries() -> None:
    amphitheater = [generate("OGE14-A01", seed).condition for seed in range(300)]
    assert any("на 1 место больше" in condition for condition in amphitheater)
    assert any("на 2 места больше" in condition for condition in amphitheater)
    assert any("на 5 мест больше" in condition for condition in amphitheater)
    cooling = [generate("OGE14-A05", seed).condition for seed in range(300)]
    assert any("через 1 минуту" in condition for condition in cooling)
    assert any("через 2 минуты" in condition for condition in cooling)
    braking = [generate("OGE14-A07", seed).condition for seed in range(300)]
    assert any("за первые 3 секунды" in condition for condition in braking)
    assert any("за первые 5 секунд" in condition for condition in braking)


def test_task14_bounce_starts_at_first_rebound_and_uses_strict_threshold() -> None:
    for seed in range(250):
        problem = generate("OGE14-G04", seed)
        h1 = problem.parameters["h1"]
        factor = problem.parameters["factor"]
        threshold = problem.parameters["threshold"]
        bounce = int(problem.exact_value)
        assert Fraction(h1, factor ** (bounce - 1)) < threshold
        if bounce > 1:
            assert Fraction(h1, factor ** (bounce - 2)) >= threshold


def test_task14_a09_source_regression_answers_days_and_preserves_painting_story() -> None:
    parameters = {"n": 4, "a1": 30, "d": 5}
    condition = _render("OGE14-A09", parameters)
    assert "150 м" in condition and "75 м" in condition
    assert "бригада маляров красит" in condition.lower()
    assert "покрасили" in condition
    assert "постро" not in condition
    assert _model("OGE14-A09", parameters) == 4
    assert _arithmetic_sum(parameters) == 150
    assert solve_condition("OGE14-A09", condition) == 4
    _, solution = _explanation("OGE14-A09", parameters, Fraction(4))
    assert "a₁+aₙ = 75 м" in solution[1]
    assert "2·150/75 = 4" in solution[2]
    assert "30" not in " ".join(solution)

    # The previous renderer changed painting to construction and supplied the
    # endpoint outputs separately; the source-locked oracle must reject it.
    previous_condition = (
        "Забор длиной 150 м нужно построить за несколько дней. В первый день "
        "построили 30 м, а в последний — 45 м. Каждый день строили на одинаковую "
        "длину больше, чем в предыдущий. За сколько дней построили забор?"
    )
    assert solve_condition("OGE14-A09", previous_condition) is None


def test_task14_a10_fipi_regression_infers_increment_without_giving_it() -> None:
    parameters = {"n": 15, "a1": 30, "d": 5, "k": 5}
    condition = _render("OGE14-A10", parameters)
    assert "За 15 дней" in condition
    assert "составило 975" in condition
    assert "первый день число приседаний составило 30" in condition
    assert "на 5 приседаний больше" not in condition
    assert _arithmetic_sum(parameters) == 975
    assert _model("OGE14-A10", parameters) == 50
    assert solve_condition("OGE14-A10", condition) == 50
    _, solution = _explanation("OGE14-A10", parameters, Fraction(50))
    assert "aₙ = 2·975/15−30 = 100" in solution[1]
    assert "= 50" in solution[2]
    assert not any("d = 5" in step for step in solution)

    # Regression for the prior text, which displayed a_k as S_n and disclosed d.
    previous_condition = (
        "За 15 дней спортсмен сделал всего 50 приседаний. Каждый день он делал "
        "на 5 приседаний больше, чем в предыдущий, а в первый день сделал 30. "
        "Сколько приседаний он сделал в 5-й день?"
    )
    assert solve_condition("OGE14-A10", previous_condition) is None


def test_task14_a05_visible_condition_retains_experiment_duration() -> None:
    problem = generate("OGE14-A05", 412218)
    assert str(problem.parameters["minutes_total"]) in problem.condition
    assert "охлаждали" in problem.condition
    assert audit_condition("OGE14-A05", problem.condition, problem.parameters)
    changed_duration = problem.condition.replace(
        f"охлаждали {problem.parameters['minutes_total']}",
        f"охлаждали {problem.parameters['minutes_total'] + 1}",
        1,
    )
    assert not audit_condition("OGE14-A05", changed_duration, problem.parameters)
