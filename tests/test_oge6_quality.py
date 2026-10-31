from app.math.generator import GENERATOR_SPECS, generate
from app.math.oracle import validate_rendered_problem
from scripts.oge6_quality_report import analyze_family


def test_all_enabled_task6_families_pass_10000_seed_exam_shape_gate() -> None:
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
