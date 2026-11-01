from __future__ import annotations

import json
import random
from fractions import Fraction
from pathlib import Path

import pytest

from app.math.formulas import (
    ALL_FAMILIES,
    ENABLED_FAMILIES,
    GENERATOR_VERSION,
    POLICY,
    R001,
    R004,
    R010,
    R013,
    R015,
    R017,
    _format_tenths,
    _round_tenths,
    check_answer,
    generate,
    solve_rendered_condition,
    validate_rendered_problem,
)
from app.math.oge12_scheduler import build_task12_candidate_batch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FILE = ROOT / "atlas" / "oge12_wording_patterns.json"


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_all_formula_families_generate_deterministic_exact_rendered_problems(
    family_id: str,
) -> None:
    first = generate(family_id, 71)
    second = generate(family_id, 71)
    assert first == second
    assert first.family_id == family_id
    assert first.generator_version == GENERATOR_VERSION
    assert first.problem_id == second.problem_id
    assert first.reference_ids
    assert first.fingerprint
    assert validate_rendered_problem(first)
    assert solve_rendered_condition(family_id, first.condition) == Fraction(
        POLICY.parse(first.correct_answer)
    )
    assert first.to_snapshot()["answer_policy_id"] == POLICY.policy_id
    assert first.to_snapshot()["answer_policy_version"] == POLICY.version
    assert first.to_snapshot()["condition"] == first.condition
    assert first.to_snapshot()["solution"] == list(first.solution)


def test_authored_research_examples_are_regression_fixtures_for_visible_oracle() -> None:
    registry = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    assert len(registry["patterns"]) == 17
    assert {item["family_id"] for item in registry["patterns"]} == set(ALL_FAMILIES)
    references = json.loads(
        (ROOT / "atlas" / "oge12_reference_structures.json").read_text(encoding="utf-8")
    )
    source_ids = {
        item["id"]: {str(task_id) for task_id in item.get("ids", [])}
        for item in references["families"]
    }
    assert all(
        str(sample["origin_task_id"]) in source_ids[sample["family_id"]]
        for sample in registry["patterns"]
    )
    for sample in registry["patterns"]:
        family_id = sample["family_id"]
        result = solve_rendered_condition(family_id, sample["authored_ready_to_use_condition"])
        expected = POLICY.parse(sample["correct_answer"])
        assert result == expected, family_id


@pytest.mark.parametrize("family_id", ENABLED_FAMILIES)
def test_enabled_family_passes_250_case_oracle_and_200_unique_acceptance(family_id: str) -> None:
    rng = random.Random(f"oge12-quality:{family_id}")
    sample = [generate(family_id, rng.randrange(2**63)) for _ in range(250)]
    assert all(validate_rendered_problem(problem) for problem in sample)
    assert all(
        solve_rendered_condition(family_id, problem.condition)
        == POLICY.parse(problem.correct_answer)
        for problem in sample
    )
    seen = {problem.fingerprint for problem in sample}
    attempts = len(sample)
    while len(seen) < 200 and attempts < 1200:
        problem = generate(family_id, rng.randrange(2**63))
        attempts += 1
        seen.add(problem.fingerprint)
    assert len(seen) >= 200
    assert attempts <= 1200


def test_answer_policy_accepts_decimal_comma_point_negative_and_tiny_values() -> None:
    assert check_answer(R001, POLICY.policy_id, POLICY.version, "5,0", "5")
    assert check_answer(R004, POLICY.policy_id, POLICY.version, "-13.9", "-13,9")
    assert check_answer(R013, POLICY.policy_id, POLICY.version, "0,0072", "0,0072")
    assert check_answer(R013, POLICY.policy_id, POLICY.version, ".00005", "0,00005")
    assert not check_answer(R013, POLICY.policy_id, POLICY.version, "1e-4", "0,0001")
    assert not check_answer(R001, "unknown", "1", "5", "5")


def test_tenths_rounding_is_exact_half_away_from_zero_and_keeps_one_decimal() -> None:
    assert _round_tenths(Fraction(5, 4)) == Fraction(13, 10)
    assert _round_tenths(Fraction(-5, 4)) == Fraction(-13, 10)
    assert _format_tenths(Fraction(-125, 9)) == "-13,9"
    assert _format_tenths(Fraction(4)) == "4,0"


def test_source_sample_rounding_and_negative_temperature_answer() -> None:
    assert solve_rendered_condition(
        R004,
        "Температура по Фаренгейту связана формулой F = 1,8·C + 32. "
        "Найдите C, если F = 6 °F. Ответ округлите до десятых.",
    ) == Fraction(-144, 10)


def test_thousand_joule_conversion_and_nonnegative_velocity() -> None:
    problem = generate(R010, 4401)
    assert "тысяч Дж" in problem.condition or "Дж" in problem.condition
    assert solve_rendered_condition(R010, problem.condition) == Fraction(
        POLICY.parse(problem.correct_answer)
    )
    assert problem.exact_value >= 0


def test_capacitor_small_values_preserve_scale_and_reject_scientific_notation() -> None:
    problem = generate(R013, 1)
    assert "10⁻⁴ Ф" in problem.condition
    sample = next(
        item
        for item in json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["patterns"]
        if item["family_id"] == R013
    )
    assert solve_rendered_condition(R013, sample["authored_ready_to_use_condition"]) == Fraction(
        8, 625
    )
    assert Fraction(POLICY.parse("0,00005")) == Fraction(1, 20000)
    assert POLICY.parse("1e-4") is None


def test_triangle_with_inradius_checks_triangle_inequality_heron_and_radius() -> None:
    sample = next(
        item
        for item in json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["patterns"]
        if item["family_id"] == R017
    )
    condition = sample["authored_ready_to_use_condition"]
    assert solve_rendered_condition(R017, condition) == Fraction(10)
    broken = condition.replace("r = 2", "r = 3")
    assert solve_rendered_condition(R017, broken) is None


def test_rendered_oracle_rejects_formula_variable_unit_and_target_mutations() -> None:
    problem = generate(R001, 81001)
    assert validate_rendered_problem(problem)
    assert solve_rendered_condition(R001, problem.condition.replace("I²", "I")) is None
    assert solve_rendered_condition(R001, problem.condition.replace("Вт", "кг", 1)) is None
    assert (
        solve_rendered_condition(
            R001, problem.condition.replace("Найдите сопротивление R", "Найдите силу тока I")
        )
        is None
    )


def test_scheduler_rotates_all_enabled_structures_and_deduplicates_recent_fingerprints() -> None:
    state: dict[str, object] = {}
    issued: list[dict[str, object]] = []
    for index in range(len(ENABLED_FAMILIES)):
        candidates = build_task12_candidate_batch(state, 95100 + index)
        assert candidates
        selected = candidates[0]
        issued.append(selected)
        state = {
            "family_queue": selected["_family_queue_after"],
            "last_family_id": selected["_last_family_after"],
            "recent_fingerprints": [item["fingerprint"] for item in issued],
        }
    families = [str(item["family_id"]) for item in issued]
    assert set(families) == set(ENABLED_FAMILIES)
    assert all(left != right for left, right in zip(families, families[1:], strict=False))
    assert len({str(item["fingerprint"]) for item in issued}) == len(issued)


def test_disabled_families_are_implemented_but_not_selected() -> None:
    assert set(ENABLED_FAMILIES) < set(ALL_FAMILIES)
    assert R015 not in ENABLED_FAMILIES
    assert R004 in ENABLED_FAMILIES
