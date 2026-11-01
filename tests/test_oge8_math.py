from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from app.math.oge8 import (
    ALL_FAMILIES,
    ENABLED_FAMILIES,
    POLICY,
    R04,
    R08,
    _oracle_text,
    generate,
    verify_problem,
)
from app.math.oge8_scheduler import build_task8_candidate_batch


def test_only_source_checked_numeric_families_are_enabled() -> None:
    assert ENABLED_FAMILIES == (R04, R08)
    assert set(ENABLED_FAMILIES) <= set(ALL_FAMILIES)


def test_atlas_keeps_unverified_structures_disabled_and_cites_active_sources() -> None:
    atlas = json.loads(Path("atlas/oge8_reference_structures.json").read_text(encoding="utf-8"))
    families = {item["family_id"]: item for item in atlas["families"]}
    assert set(atlas["metadata"]["enabled_families"]) == set(ENABLED_FAMILIES)
    assert families[R04]["active_reference_ids"] == ["137285"]
    assert families[R08]["active_reference_ids"] == ["400942"]
    assert sum(item["enabled"] for item in families.values()) == 2
    assert families["OGE08-R07"]["enabled"] is False
    assert families["OGE08-R15"]["enabled"] is False


@pytest.mark.parametrize("family", ENABLED_FAMILIES)
def test_generator_is_deterministic_and_rendered_condition_has_independent_oracle(
    family: str,
) -> None:
    for seed in range(250):
        first = generate(family, seed)
        second = generate(family, seed)
        assert first == second
        assert verify_problem(first)
        assert _oracle_text(first.condition) == first.exact_value
        assert POLICY.format(first.exact_value) == first.correct_answer
        assert first.to_snapshot()["expression_ast"]


def test_enabled_families_reach_200_distinct_conditions_within_budget() -> None:
    for family in ENABLED_FAMILIES:
        fingerprints: set[str] = set()
        attempts = 0
        while len(fingerprints) < 200 and attempts < 1_200:
            fingerprints.add(generate(family, attempts).fingerprint)
            attempts += 1
        assert len(fingerprints) >= 200
        assert attempts <= 1_200


@pytest.mark.parametrize("family,seed", [(R04, 1729), (R08, 14)])
def test_oracle_rejects_visible_condition_mutation(family: str, seed: int) -> None:
    problem = generate(family, seed)
    changed = replace(problem, condition=problem.condition.replace("√", "∛", 1))
    assert not verify_problem(changed)


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("Вычислите: (sqrt(18)+2)**2-4*sqrt(18)", Fraction(22)),
        ("Вычислите: sqrt(9)", Fraction(3)),
        ("Вычислите: √(0)", Fraction(0)),
        ("Вычислите: (-2)**4", Fraction(16)),
        ("Вычислите: -2**4", Fraction(-16)),
    ],
)
def test_visible_text_oracle_preserves_radicals_signs_and_precedence(
    condition: str, expected: Fraction
) -> None:
    assert _oracle_text(condition) == expected


@pytest.mark.parametrize(
    "condition",
    [
        "Вычислите: sqrt(-1)",
        "Вычислите: 1/0",
        "Вычислите: 0**-2",
        "Вычислите: (√(5)+2)^2+6·√(5)",
    ],
)
def test_visible_text_oracle_rejects_invalid_or_changed_expression(condition: str) -> None:
    with pytest.raises((ValueError, ZeroDivisionError)):
        _oracle_text(condition)


def test_candidate_scheduler_cycles_families_and_avoids_recent_fingerprints() -> None:
    first = build_task8_candidate_batch({}, 2026)
    assert {item["family_id"] for item in first} == set(ENABLED_FAMILIES)
    recent = [first[0]["fingerprint"]]
    second = build_task8_candidate_batch({"recent_fingerprints": recent}, 2026)
    assert all(item["fingerprint"] not in recent for item in second)
