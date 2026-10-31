from dataclasses import replace
from fractions import Fraction

import pytest

from app.math.ast import Binary, Decimal, render
from app.math.generator import GENERATOR_SPECS, generate
from app.math.oracle import validate_rendered_problem
from app.math.scheduler import build_candidate_batch, build_family_deck
from scripts.oge6_quality_report import analyze_family


def test_all_enabled_task6_families_pass_250_sample_exam_shape_gate() -> None:
    reports = [analyze_family(spec) for spec in GENERATOR_SPECS]
    assert len(reports) == 10
    assert all(report["sample_count"] == 250 for report in reports)
    assert all(report["acceptance_unique_count"] >= 200 for report in reports)
    assert all(report["reference_structure_match"] for report in reports)


def test_generator_is_deterministic_and_rendered_condition_has_independent_oracle() -> None:
    for spec in GENERATOR_SPECS:
        first = generate(spec.family_id, 742)
        second = generate(spec.family_id, 742)
        assert first.to_snapshot() == second.to_snapshot()
        validate_rendered_problem(first)


def test_decimal_rendering_preserves_exam_operand_scale() -> None:
    assert render(Decimal(50, 1)) == "5,0"
    assert render(Decimal(500, 2)) == "5,00"


@pytest.mark.parametrize(
    ("family_id", "condition"),
    [
        ("OGE06-F004-DEC-ADD", "Вычислите: 5 + 4,6"),
        ("OGE06-F004-DEC-SUB", "Вычислите: 5,0 - 4,6"),
        ("OGE06-F004-DEC-MUL", "Вычислите: 5 · 4,6"),
    ],
)
def test_oracle_rejects_rendered_decimal_family_shape_changes(
    family_id: str, condition: str
) -> None:
    problem = generate(family_id, 742)
    malformed = replace(
        problem,
        expression=Binary("+", Decimal(50, 1), Decimal(46, 1)),
        condition=condition,
        exact_value=Fraction(48, 5),
        correct_answer="9,6",
    )
    with pytest.raises(AssertionError, match="Displayed"):
        validate_rendered_problem(malformed)


def test_family_scheduler_cycles_all_confirmed_enabled_types_before_extras() -> None:
    deck = build_family_deck(104)
    enabled = {spec.family_id for spec in GENERATOR_SPECS}
    assert len(deck[: len(enabled)]) == len(enabled)
    assert set(deck[: len(enabled)]) == enabled
    assert all(family_id in enabled for family_id in deck)


def test_scheduler_filters_recent_fingerprints() -> None:
    first_batch = build_candidate_batch({}, 209)
    first_fingerprint = str(first_batch[0]["fingerprint"])
    filtered = build_candidate_batch({"recent_fingerprints": [first_fingerprint]}, 209)
    assert filtered
    assert all(item["fingerprint"] != first_fingerprint for item in filtered)
