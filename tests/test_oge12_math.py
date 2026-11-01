from __future__ import annotations

import json
import random
import re
from dataclasses import replace
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
    # R003's input domain contains 201 values; pin a stream that covers 200
    # without raising the historical 1,200-attempt acceptance bound.
    suffix = ":coverage" if family_id == "OGE12-R003" else ""
    rng = random.Random(f"oge12-quality:{family_id}{suffix}")
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


FORMULA_MUTATIONS = {
    "OGE12-R001": ("I²·R", "I·R"),
    "OGE12-R002": ("ω²·R", "ω·R"),
    "OGE12-R003": ("1,8·C", "1,7·C"),
    "OGE12-R004": ("1,8·C", "1,7·C"),
    "OGE12-R005": ("sin(α)/2", "sin(α)/3"),
    "OGE12-R006": ("d₁·d₂/2", "d₁·d₂/3"),
    "OGE12-R007": ("a·h/2", "a·h/3"),
    "OGE12-R008": ("(a+b)·h/2", "(a+b)·h/3"),
    "OGE12-R009": ("S·h/3", "S·h/4"),
    "OGE12-R010": ("m·v²/2", "m·v²/3"),
    "OGE12-R011": ("m·g·h", "m·g·2h"),
    "OGE12-R012": ("ρ·g·V", "ρ·g·2V"),
    "OGE12-R013": ("U²/2", "U²/3"),
    "OGE12-R014": ("a+b·n", "a+b+n"),
    "OGE12-R015": ("11·(t−5)", "12·(t−5)"),
    "OGE12-R016": ("sin(α)/2", "sin(α)/3"),
    "OGE12-R017": ("(a+b+c)·r/2", "(a+b+c)·r/3"),
}

UNIT_MUTATIONS = {
    "OGE12-R001": (" Вт", " кг"),
    "OGE12-R002": ("м/с²", "км/ч"),
    "OGE12-R003": ("°C", "°F"),
    "OGE12-R004": ("°F", "°C"),
    "OGE12-R005": ("четырёхугольника", "треугольника"),
    "OGE12-R006": ("м²", "см²"),
    "OGE12-R007": ("м²", "см²"),
    "OGE12-R008": ("м²", "см²"),
    "OGE12-R009": ("м³", "см³"),
    "OGE12-R010": (" кг,", " г,"),
    "OGE12-R011": (" Дж и h", " Вт и h"),
    "OGE12-R012": ("ρ = 1000", "ρ = 21000"),
    "OGE12-R013": ("10⁻⁴ Ф", "10⁻³ Ф"),
    "OGE12-R014": (" руб.", " долл."),
    "OGE12-R015": (" минут", " секунд"),
    "OGE12-R016": ("стороны", "диагонали"),
    "OGE12-R017": ("сторонами", "углами"),
}

TARGET_MUTATIONS = {
    "OGE12-R001": ("Найдите сопротивление R", "Найдите силу тока I"),
    "OGE12-R002": ("найдите R", "найдите ускорение a"),
    "OGE12-R003": ("Какая температура по Фаренгейту", "Какая температура по Цельсию"),
    "OGE12-R004": ("Найдите C", "Найдите F"),
    "OGE12-R005": ("Найдите sin(α)", "Найдите d₁"),
    "OGE12-R006": ("Найдите d₁", "Найдите d₂"),
    "OGE12-R007": ("Найдите сторону a", "Найдите высоту h"),
    "OGE12-R008": ("Найдите h", "Найдите a"),
    "OGE12-R009": ("Найдите высоту", "Найдите объём V"),
    "OGE12-R010": ("Найдите скорость", "Найдите энергию"),
    "OGE12-R011": ("Найдите массу", "Найдите высоту"),
    "OGE12-R012": ("Найдите F", "Найдите V"),
    "OGE12-R013": ("Найдите W", "Найдите U"),
    "OGE12-R014": ("Найдите C", "Найдите n"),
    "OGE12-R015": ("Найдите стоимость", "Найдите время"),
    "OGE12-R016": ("Найдите S", "Найдите b"),
    "OGE12-R017": ("Найдите c", "Найдите a"),
}


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_each_family_oracle_rejects_formula_unit_and_target_mutations(family_id: str) -> None:
    problem = generate(family_id, 711)
    for mutations in (FORMULA_MUTATIONS, UNIT_MUTATIONS, TARGET_MUTATIONS):
        original, mutated = mutations[family_id]
        assert original in problem.condition, (family_id, original)
        condition = problem.condition.replace(
            original, mutated, 1 if mutations is not UNIT_MUTATIONS else -1
        )
        assert solve_rendered_condition(family_id, condition) is None, family_id


LEFT_SIDE_MUTATIONS = {
    "OGE12-R001": ("P = I²·R", "Q = I²·R"),
    "OGE12-R002": ("a = ω²·R", "F = ω²·R"),
    "OGE12-R003": ("F = 1,8·C + 32", "G = 1,8·C + 32"),
    "OGE12-R004": ("F = 1,8·C + 32", "G = 1,8·C + 32"),
    "OGE12-R005": ("S = d₁·d₂·sin(α)/2", "A = d₁·d₂·sin(α)/2"),
    "OGE12-R006": ("S = d₁·d₂/2", "A = d₁·d₂/2"),
    "OGE12-R007": ("S = a·h/2", "A = a·h/2"),
    "OGE12-R008": ("S = (a+b)·h/2", "A = (a+b)·h/2"),
    "OGE12-R009": ("V = S·h/3", "A = S·h/3"),
    "OGE12-R010": ("E = m·v²/2", "W = m·v²/2"),
    "OGE12-R011": ("P = m·g·h", "Q = m·g·h"),
    "OGE12-R012": ("F = ρ·g·V", "E = ρ·g·V"),
    "OGE12-R013": ("W = C·U²/2", "E = C·U²/2"),
    "OGE12-R014": ("C = a+b·n", "K = a+b·n"),
    "OGE12-R015": ("C = 150 + 11·(t−5)", "K = 150 + 11·(t−5)"),
    "OGE12-R016": ("S = b·c·sin(α)/2", "A = b·c·sin(α)/2"),
    "OGE12-R017": ("S = (a+b+c)·r/2", "A = (a+b+c)·r/2"),
}


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_each_family_oracle_rejects_left_side_formula_mutation(family_id: str) -> None:
    problem = generate(family_id, 711)
    original, mutated = LEFT_SIDE_MUTATIONS[family_id]
    assert original in problem.condition, (family_id, original, problem.condition)
    condition = problem.condition.replace(original, mutated, 1)
    assert solve_rendered_condition(family_id, condition) is None, family_id


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_every_solution_step_and_answer_metadata_are_validated(family_id: str) -> None:
    problem = generate(family_id, 712)
    for index in range(len(problem.solution)):
        steps = list(problem.solution)
        steps[index] = f"Подменённый шаг {index}"
        assert not validate_rendered_problem(replace(problem, solution=tuple(steps)))
    assert not validate_rendered_problem(replace(problem, exact_value=problem.exact_value + 1))
    assert not validate_rendered_problem(replace(problem, correct_answer="123456"))
    assert not validate_rendered_problem(replace(problem, formula="неверная формула"))
    assert not validate_rendered_problem(replace(problem, target="wrong"))
    assert not validate_rendered_problem(replace(problem, units={"answer": "wrong"}))
    assert not validate_rendered_problem(replace(problem, constraints=("wrong",)))


DISPLAYED_GIVEN_MUTATIONS = {
    "OGE12-R001": r"Мощность P равна ([\d,.]+) Вт",
    "OGE12-R002": r"ω = ([\d,.]+) с⁻¹",
    "OGE12-R003": r"соответствует ([−-]?[\d,.]+) °C",
    "OGE12-R004": r"если F = ([−-]?[\d,.]+) °F",
    "OGE12-R005": r"d₁ = ([\d,.]+)",
    "OGE12-R006": r"если S = ([\d,.]+) м²",
    "OGE12-R007": r"если S = ([\d,.]+) м²",
    "OGE12-R008": r", S = ([\d,.]+) м²",
    "OGE12-R009": r"если V = ([\d,.]+) м³",
    "OGE12-R010": r"массой ([\d,.]+) кг",
    "OGE12-R011": r"если P = ([\d,.]+) Дж",
    "OGE12-R012": r"объёмом ([\d,.]+) м³",
    "OGE12-R013": r"U = ([\d,.]+) В",
    "OGE12-R014": r"из ([\d]+) колец",
    "OGE12-R015": r"длительностью ([\d,.]+) минут",
    "OGE12-R016": r"b = ([\d,.]+)",
    "OGE12-R017": r", если S = ([\d,.]+),",
}


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_each_family_rejects_a_changed_displayed_numeric_given(family_id: str) -> None:
    problem = generate(family_id, 711)
    match = re.search(DISPLAYED_GIVEN_MUTATIONS[family_id], problem.condition)
    assert match is not None, (family_id, problem.condition)
    original = Fraction(match.group(1).replace("−", "-").replace(",", "."))
    replacement = POLICY.format(original + 1)
    condition = (
        problem.condition[: match.start(1)]
        + replacement
        + problem.condition[match.end(1) :]
    )
    assert not validate_rendered_problem(replace(problem, condition=condition)), family_id


def test_oracle_reads_gravity_and_density_as_numeric_givens() -> None:
    r011 = generate("OGE12-R011", 711).condition
    assert solve_rendered_condition("OGE12-R011", r011) is not None
    assert solve_rendered_condition("OGE12-R011", r011.replace("g = 9,8", "g = 19,8")) is None
    r012 = generate("OGE12-R012", 711).condition
    assert solve_rendered_condition("OGE12-R012", r012) is not None
    assert solve_rendered_condition("OGE12-R012", r012.replace("ρ = 1000", "ρ = 21000")) is None
    assert solve_rendered_condition("OGE12-R012", r012.replace("g = 9,8", "g = 19,8")) is None


def test_enabled_solution_steps_reject_wrong_rearrangements_and_substitutions() -> None:
    solution_mutations = {
        "OGE12-R001": (1, "P/I²", "P/I"),
        "OGE12-R002": (1, "a/ω²", "a/ω"),
        "OGE12-R003": (1, "1,8·(", "1,7·("),
        "OGE12-R004": (1, "/1,8", "/1,7"),
        "OGE12-R005": (1, "2S/", "3S/"),
        "OGE12-R010": (1, "2E/m", "E/m"),
        "OGE12-R011": (1, "P/(g·h)", "P/h"),
        "OGE12-R012": (1, "1000·9,8", "21000·9,8"),
    }
    assert set(solution_mutations) == set(ENABLED_FAMILIES)
    for family_id, (index, original, mutated) in solution_mutations.items():
        problem = generate(family_id, 712)
        steps = list(problem.solution)
        assert original in steps[index], (family_id, steps[index])
        steps[index] = steps[index].replace(original, mutated, 1)
        broken = replace(problem, solution=tuple(steps))
        assert not validate_rendered_problem(broken), family_id


def test_r005_answer_diversity_uses_exact_geometric_sine_values_not_angle_table() -> None:
    answers: set[Fraction] = set()
    for seed in range(250):
        r005 = generate("OGE12-R005", seed)
        answer = POLICY.parse(r005.correct_answer)
        assert answer is not None and Fraction(0) < answer <= 1
        assert answer.denominator in {1, 2, 5, 10}
        assert solve_rendered_condition("OGE12-R005", r005.condition) == answer
        assert r005.to_snapshot()["content_provenance"] == "generated_analogue"
        answers.add(answer)
    assert len(answers) >= 9

    # R016 does ask students to use a standard-angle table. Keep its domain
    # deliberately constrained; R005's broader range is inferred from its
    # formula and confirmed source example 311543 (sin(alpha) = 0.4).
    for seed in range(250):
        r016 = generate("OGE12-R016", seed)
        angle = next(value for value in (30, 90, 150) if f"α = {value}°" in r016.condition)
        assert (
            solve_rendered_condition(
                "OGE12-R016", r016.condition.replace(f"α = {angle}°", "α = 37°")
            )
            is None
        )
