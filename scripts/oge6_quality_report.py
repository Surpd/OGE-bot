from __future__ import annotations

import argparse
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import cast

from app.math.analysis import (
    answer_metrics,
    calculation_diagnostics,
    expression_metrics,
)
from app.math.answer_policy import decimal_places
from app.math.generator import GENERATOR_VERSION, generate, generate_random
from app.math.oracle import validate_rendered_problem
from app.math.registry import GENERATOR_SPECS, GeneratorSpec

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / f"oge6-{GENERATOR_VERSION}-quality.json"
SAMPLE_COUNTS = {"quick": 40, "main": 250, "acceptance": 250}
ACCEPTANCE_ATTEMPT_LIMIT = 1_200
ACCEPTANCE_UNIQUE_TARGET = 200


def _manual_rejections(spec: GeneratorSpec, diagnostics: dict[str, int]) -> list[str]:
    limits = spec.manual_limits
    rejected: list[str] = []
    checks = {
        "max_intermediate_numerator": limits.max_intermediate_numerator,
        "max_intermediate_denominator": limits.max_intermediate_denominator,
        "max_common_denominator": limits.max_common_denominator,
        "max_integer_factor": limits.max_integer_factor,
        "estimated_manual_steps": limits.max_estimated_steps,
    }
    for metric, limit in checks.items():
        if diagnostics[metric] > limit:
            rejected.append(f"{metric}>{limit}")
    return rejected


def analyze_family(
    spec: GeneratorSpec,
    *,
    seed_count: int = SAMPLE_COUNTS["main"],
    acceptance_limit: int = ACCEPTANCE_ATTEMPT_LIMIT,
) -> dict[str, object]:
    family_id = spec.family_id
    problems = [generate(family_id, seed) for seed in range(seed_count)]
    for problem in problems:
        validate_rendered_problem(problem)
    expressions: set[str] = set()
    fingerprints: set[str] = set()
    problem_ids: set[str] = set()
    structures: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    actions: Counter[int] = Counter()
    groups: Counter[int] = Counter()
    complexity: Counter[int] = Counter()
    denominators: Counter[int] = Counter()
    operand_places: Counter[int] = Counter()
    manual_histograms: dict[str, Counter[int]] = {
        key: Counter()
        for key in (
            "max_intermediate_numerator",
            "max_intermediate_denominator",
            "max_common_denominator",
            "max_integer_factor",
            "arithmetic_actions",
            "transformation_count",
            "cancellation_count",
            "estimated_manual_steps",
        )
    }
    rejection_reasons: Counter[str] = Counter()
    negative_operands = zero_operands = total_operands = 0
    answer_classes: Counter[str] = Counter()
    negative_answers = zero_answers = 0
    absolute_answers: list[Fraction] = []

    for problem in problems:
        expressions.add(problem.condition)
        fingerprints.add(problem.fingerprint)
        problem_ids.add(problem.problem_id)
        metrics = expression_metrics(problem.expression)
        signature = cast(str, metrics["signature"])
        structures[signature] += 1
        operations.update(cast(dict[str, int], metrics["operations"]))
        action_count = cast(int, metrics["action_count"])
        group_count = cast(int, metrics["group_count"])
        actions[action_count] += 1
        groups[group_count] += 1
        fractions = cast(list[int], metrics["fraction_denominators"])
        decimal_digits = cast(list[int], metrics["decimal_operand_places"])
        complexity[action_count + group_count + max(0, len(fractions) - 1)] += 1
        denominators.update(fractions)
        operand_places.update(decimal_digits)
        negative_operands += cast(int, metrics["negative_operands"])
        zero_operands += cast(int, metrics["zero_operands"])
        total_operands += cast(int, metrics["operand_count"])
        answer_value = problem.answer_policy.parse(problem.correct_answer)
        if answer_value is None:
            raise AssertionError(f"Unparseable generated answer for {family_id}")
        answer = answer_metrics(answer_value)
        answer_classes[cast(str, answer["answer_class"])] += 1
        negative_answers += bool(answer["negative"])
        zero_answers += bool(answer["zero"])
        absolute_answers.append(abs(answer_value))
        manual = calculation_diagnostics(problem.expression)
        for key, histogram in manual_histograms.items():
            histogram[manual[key]] += 1
        rejection_reasons.update(_manual_rejections(spec, manual))

    manual_maxima = {key: max(histogram, default=0) for key, histogram in manual_histograms.items()}
    structure_matches = (
        len(structures) == 1 and next(iter(structures), None) == spec.expression_shape
    )
    acceptance_conditions = set(expressions)
    acceptance_attempts = seed_count
    if acceptance_limit > seed_count and len(acceptance_conditions) < ACCEPTANCE_UNIQUE_TARGET:
        for seed in range(seed_count, acceptance_limit):
            candidate = generate(family_id, seed)
            validate_rendered_problem(candidate)
            acceptance_attempts = seed + 1
            if _manual_rejections(spec, calculation_diagnostics(candidate.expression)):
                continue
            acceptance_conditions.add(candidate.condition)
            if len(acceptance_conditions) >= ACCEPTANCE_UNIQUE_TARGET:
                break

    report: dict[str, object] = {
        "family_id": family_id,
        "reference_structure_id": spec.reference_structure_id,
        "source_ids": list(spec.source_ids),
        "source_weight": spec.selection_weight,
        "sample_count": seed_count,
        "valid_sample_count": seed_count - sum(rejection_reasons.values()),
        "rejected_count": sum(rejection_reasons.values()),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "unique_rendered_conditions": len(expressions),
        "unique_fingerprints": len(fingerprints),
        "unique_problem_ids": len(problem_ids),
        "unique_ast_structures": len(structures),
        "ast_structure_histogram": dict(structures),
        "reference_structure_match": structure_matches,
        "expected_structure": spec.expression_shape,
        "operations": dict(sorted(operations.items())),
        "action_count_histogram": dict(sorted(actions.items())),
        "group_count_histogram": dict(sorted(groups.items())),
        "calculation_complexity_index_histogram": dict(sorted(complexity.items())),
        "fraction_denominator_histogram": dict(sorted(denominators.items())),
        "decimal_operand_places_histogram": dict(sorted(operand_places.items())),
        "operand_signs": {
            "negative": negative_operands,
            "zero": zero_operands,
            "nonnegative": total_operands - negative_operands - zero_operands,
        },
        "answer_format": spec.policy.answer_format.value,
        "answer_class_histogram": dict(sorted(answer_classes.items())),
        "negative_answers": negative_answers,
        "zero_answers": zero_answers,
        "absolute_answer_min": str(min(absolute_answers)),
        "absolute_answer_max": str(max(absolute_answers)),
        "manual_limits": {
            "max_intermediate_numerator": spec.manual_limits.max_intermediate_numerator,
            "max_intermediate_denominator": spec.manual_limits.max_intermediate_denominator,
            "max_common_denominator": spec.manual_limits.max_common_denominator,
            "max_integer_factor": spec.manual_limits.max_integer_factor,
            "max_estimated_steps": spec.manual_limits.max_estimated_steps,
        },
        "manual_diagnostics_maxima": manual_maxima,
        "acceptance_unique_target": ACCEPTANCE_UNIQUE_TARGET,
        "acceptance_attempt_limit": acceptance_limit,
        "acceptance_unique_count": len(acceptance_conditions),
        "acceptance_attempts_used": min(acceptance_attempts, acceptance_limit),
        "acceptance_gate_passed": (
            acceptance_limit == 0 or len(acceptance_conditions) >= ACCEPTANCE_UNIQUE_TARGET
        ),
        "examples": [
            {"condition": problem.condition, "answer": problem.correct_answer, "seed": problem.seed}
            for problem in problems[:3]
        ],
    }
    if (
        not structure_matches
        or len(problem_ids) != seed_count
        or sum(rejection_reasons.values()) > 0
        or (acceptance_limit > 0 and len(acceptance_conditions) < ACCEPTANCE_UNIQUE_TARGET)
    ):
        raise AssertionError(f"OGE-6 quality gate failed for {family_id}: {report}")
    return report


def build_report(level: str) -> dict[str, object]:
    sample_count = SAMPLE_COUNTS[level]
    acceptance_limit = 0 if level == "quick" else ACCEPTANCE_ATTEMPT_LIMIT
    families = [
        analyze_family(spec, seed_count=sample_count, acceptance_limit=acceptance_limit)
        for spec in GENERATOR_SPECS
    ]
    draw_count = sample_count * len(GENERATOR_SPECS)
    draws = [generate_random(seed) for seed in range(draw_count)]
    actual_weights = Counter(problem.family_id for problem in draws)
    actual_answers: Counter[str] = Counter()
    weighted_answer_values: list[Fraction] = []
    for problem in draws:
        answer_value = problem.answer_policy.parse(problem.correct_answer)
        if answer_value is None:
            raise AssertionError("Unparseable weighted answer")
        weighted_answer_values.append(answer_value)
        actual_answers[cast(str, answer_metrics(answer_value)["answer_class"])] += 1

    source_answers = {"integer": 2, "decimal_1_places": 10, "decimal_2_places": 5}
    full_catalog_answers = {"integer": 7, "decimal_1_places": 11, "decimal_2_places": 5}
    total_variation = (
        sum(
            (
                abs(
                    Fraction(actual_answers.get(category, 0), len(draws))
                    - Fraction(source_answers.get(category, 0), 17)
                )
                for category in set(source_answers) | set(actual_answers)
            ),
            Fraction(0),
        )
        / 2
    )
    negative_count = sum(value < 0 for value in weighted_answer_values)
    sign_variation = Fraction(abs(negative_count * 17 - 5 * len(draws)), 2 * len(draws) * 17)
    abs_values = [abs(value) for value in weighted_answer_values]
    return {
        "report_version": 2,
        "run_level": level,
        "generator_version": GENERATOR_VERSION,
        "sample_count_per_family": sample_count,
        "acceptance_attempt_limit": acceptance_limit,
        "acceptance_unique_target": ACCEPTANCE_UNIQUE_TARGET,
        "prototype_registry": "atlas/oge6_reference_structures.json",
        "catalog_weight_basis": (
            "unique prototypes of enabled families; preliminary, not exam population frequency"
        ),
        "family_reports": families,
        "weighted_random_draws": {
            "count": draw_count,
            "family_distribution": dict(sorted(actual_weights.items())),
            "answer_class_distribution": dict(sorted(actual_answers.items())),
            "negative_answers": negative_count,
            "zero_answers": sum(value == 0 for value in weighted_answer_values),
            "three_or_more_decimal_places": sum(
                1
                for value in weighted_answer_values
                if (places := decimal_places(value)) is not None and places >= 3
            ),
            "absolute_answer_min": str(min(abs_values)),
            "absolute_answer_max": str(max(abs_values)),
            "enabled_prototype_answer_class_reference": source_answers,
            "full_catalog_answer_class_reference": full_catalog_answers,
            "catalog_negative_answers": 5,
            "catalog_zero_answers": 0,
            "catalog_3_plus_places": 0,
            "enabled_reference_sample_size": 17,
            "disabled_confirmed_reference_prototypes": 6,
            "answer_distribution_total_variation": {
                "numerator": total_variation.numerator,
                "denominator": total_variation.denominator,
            },
            "negative_answer_rate_total_variation": {
                "numerator": sign_variation.numerator,
                "denominator": sign_variation.denominator,
            },
            "reference_status": (
                "preliminary; small catalog prototype sample, not representative frequency estimate"
            ),
        },
        "uncovered_confirmed_types": [
            {
                "structure_id": "oge6.fraction.reciprocal_of_unit_fraction_sum",
                "source_ids": ["463020"],
                "unique_with_reference_ranges": 50,
                "reason": (
                    "Finite 50-condition capacity is an allowed documented exception to the "
                    "mass-family 200-unique target, but this type remains disabled until exact "
                    "rendering and scheduler exhaustion/fallback regression tests pass."
                ),
            },
            {
                "structure_id": "oge6.decimal.quotient_in_fraction_bar",
                "source_ids": ["348647", "438264", "438308", "438339", "438368"],
                "unique_with_reference_ranges": 43,
                "reason": (
                    "Finite 43-pair capacity is an allowed documented exception to the "
                    "mass-family 200-unique target, but this type remains disabled until exact "
                    "rendering and scheduler exhaustion/fallback regression tests pass."
                ),
            },
        ],
        "unconfirmed_disabled_types": [
            "ratios/proportions",
            "powers/order of operations",
            "arbitrary multi-step expressions",
            "ordinary fraction plus decimal fraction in one chain",
        ],
        "quality_gate_rejections": {},
        "rejection_note": (
            "Every sampled output passed exact oracle, answer policy, reference AST shape, "
            "and per-family manual-computation limits."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=tuple(SAMPLE_COUNTS), default="main")
    args = parser.parse_args()
    report = build_report(args.level)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    family_reports = cast(list[dict[str, object]], report["family_reports"])
    print(
        f"report={OUTPUT.relative_to(ROOT)} level={args.level} "
        f"families={len(family_reports)} samples_per_family={SAMPLE_COUNTS[args.level]}"
    )
    print(
        "minimum_unique="
        f"{min(cast(int, row['unique_rendered_conditions']) for row in family_reports)} "
        "minimum_acceptance_capacity="
        f"{min(cast(int, row['acceptance_unique_count']) for row in family_reports)}"
    )


if __name__ == "__main__":
    main()
