from __future__ import annotations

from fractions import Fraction

import pytest

from app.math.progressions import (
    A04,
    A11,
    ALL_FAMILIES,
    ENABLED_FAMILIES,
    FAMILY_STATUS,
    SOURCE_IDS,
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
        assert solve_condition(family, first.condition) == first.exact_value
        assert first.correct_answer
        assert first.to_snapshot()["content_provenance"] == "generated_analogue"


@pytest.mark.parametrize("family", IMPLEMENTED)
def test_task14_visible_text_mutations_are_rejected(family: str) -> None:
    problem = generate(family, 2114)
    text = problem.condition
    assert not audit_condition(family, text + " ", problem.parameters)
    mutated = text.replace("м", "км", 1) if "м" in text else text.replace("см", "мм", 1)
    assert not audit_condition(family, mutated, problem.parameters)
    if family in {
        "OGE14-A05",
        "OGE14-A06",
        "OGE14-A07",
        "OGE14-A08",
        "OGE14-G01",
        "OGE14-G02",
        "OGE14-G03",
    }:
        number = next((part for part in text.split() if part.isdigit()), None)
        assert number is not None
        changed = text.replace(number, str(int(number) + 1), 1)
        assert not audit_condition(family, changed, problem.parameters)


def test_task14_semantic_mutations_change_or_invalidate_independent_answer() -> None:
    cases = (
        ("OGE14-A05", "уменьшалась", "увеличивалась"),
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
