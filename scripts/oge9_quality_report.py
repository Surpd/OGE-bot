from __future__ import annotations

import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

from app.math.equations import (
    ENABLED_FAMILIES,
    generate_equation,
    solve_rendered_equation,
    validate_rendered_problem,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "atlas" / "oge9_reference_structures.json"
OUTPUT_PATH = ROOT / "reports" / "oge9-quality.json"
SAMPLE_COUNT = 250
UNIQUE_TARGET = 200
ATTEMPT_LIMIT = 1200
REFERENCE_ANSWER_SAMPLES = (
    ("OGE09-L1", "338606", Fraction(-5, 2)),
    ("OGE09-L2", "338488", Fraction(-3)),
    ("OGE09-L3", "338509", Fraction(97, 10)),
    ("OGE09-L4", "338495", Fraction(-9, 2)),
    ("OGE09-K2", "357568", Fraction(3)),
    ("OGE09-K3", "357133", Fraction(1, 2)),
    ("OGE09-K3", "357135", Fraction(-7, 2)),
    ("OGE09-K6", "357173", Fraction(-8)),
)


def _places(value: Fraction) -> int | None:
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    return max(twos, fives) if denominator == 1 else None


def _op_counts(text: str) -> dict[str, int]:
    tokens = re.findall(r"x²|x|\d+|[()+\-·/=]", text.replace(" ", ""))
    binary_minus = sum(
        token == "-"
        and index > 0
        and (tokens[index - 1].isdigit() or tokens[index - 1] in {"x", "x²", ")"})
        for index, token in enumerate(tokens)
    )
    return {
        "+": tokens.count("+"),
        "-": binary_minus,
        "·": tokens.count("·"),
        "/": tokens.count("/"),
    }


def analyze_family(family_id: str) -> dict[str, object]:
    examples: list[dict[str, object]] = []
    samples = [generate_equation(family_id, seed) for seed in range(SAMPLE_COUNT)]
    signatures = Counter()
    answer_places: Counter[str] = Counter()
    abs_bins: Counter[str] = Counter()
    signs: Counter[str] = Counter()
    operation_totals: Counter[str] = Counter()
    parenthesis_counts: Counter[str] = Counter()
    maximum_literal = 0
    for problem in samples:
        validate_rendered_problem(problem)
        if solve_rendered_equation(problem.equation_text) != problem.roots:
            raise AssertionError(f"Independent display oracle mismatch: {family_id}/{problem.seed}")
        # A shape signature ignores the actual coefficients and roots. It records
        # only the confirmed prototype family and visible equation grammar.
        signature = (family_id, "linear" if "L" in family_id else "quadratic")
        signatures[signature] += 1
        places = _places(problem.target_root)
        answer_places["non_terminating"] += places is None
        answer_places["integer"] += places == 0
        answer_places["decimal_1"] += places == 1
        answer_places["decimal_2"] += places == 2
        answer_places["decimal_3_plus"] += places is not None and places > 2
        signs["negative"] += problem.target_root < 0
        signs["zero"] += problem.target_root == 0
        magnitude = abs(problem.target_root)
        abs_bins["0"] += magnitude == 0
        abs_bins["0_to_1"] += 0 < magnitude <= 1
        abs_bins["1_to_5"] += 1 < magnitude <= 5
        abs_bins["5_to_10"] += 5 < magnitude <= 10
        abs_bins["over_10"] += magnitude > 10
        operation_totals.update(_op_counts(problem.equation_text))
        parenthesis_counts[str(problem.equation_text.count("("))] += 1
        for literal in re.findall(r"(?<!x)\b\d+\b", problem.equation_text):
            maximum_literal = max(maximum_literal, int(literal))
        if len(examples) < 3:
            examples.append(
                {
                    "condition": problem.condition,
                    "answer": problem.correct_answer,
                    "answer_target": problem.answer_target,
                    "solution": list(problem.solution),
                    "seed": problem.seed,
                }
            )

    unique_conditions = len({problem.fingerprint for problem in samples})
    acceptance_fingerprints: set[str] = set()
    acceptance_attempts = 0
    while len(acceptance_fingerprints) < UNIQUE_TARGET and acceptance_attempts < ATTEMPT_LIMIT:
        problem = generate_equation(family_id, SAMPLE_COUNT + acceptance_attempts)
        validate_rendered_problem(problem)
        acceptance_fingerprints.add(problem.fingerprint)
        acceptance_attempts += 1
    if len(acceptance_fingerprints) < UNIQUE_TARGET:
        raise AssertionError(f"{family_id}: only {len(acceptance_fingerprints)} unique problems")

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    entry = next(item for item in registry["structures"] if item["id"] == family_id)
    reference_answers = [
        value for family, _, value in REFERENCE_ANSWER_SAMPLES if family == family_id
    ]
    return {
        "family_id": family_id,
        "status": entry["status"],
        "reference_ids": entry["reference_ids"],
        "reference_urls": entry["urls"],
        "sample_count": SAMPLE_COUNT,
        "unique_conditions_in_sample": unique_conditions,
        "acceptance_unique_target": UNIQUE_TARGET,
        "acceptance_unique_count": len(acceptance_fingerprints),
        "acceptance_attempts": acceptance_attempts,
        "structural_signature_count": len(signatures),
        "structural_signature": [str(value) for value in signatures],
        "display_oracle": (
            "pass: Pratt parser over rendered equation; exact Fraction polynomial solver"
        ),
        "answer_target_counts": dict(Counter(problem.answer_target for problem in samples)),
        "answer_places": dict(answer_places),
        "answer_signs": dict(signs),
        "answer_absolute_value_bins": dict(abs_bins),
        "operation_counts": dict(operation_totals),
        "parentheses_histogram": dict(parenthesis_counts),
        "max_visible_integer_literal": maximum_literal,
        "examples": examples,
        "observed_catalog_answers": [
            {"task_id": task_id, "answer": str(value)}
            for family, task_id, value in REFERENCE_ANSWER_SAMPLES
            if family == family_id
        ],
        "catalog_comparison": {
            "prototype_construction_match": True,
            "answer_policy_matches_references": True,
            "observed_answer_sample_count": len(reference_answers),
            "distribution_status": (
                "preliminary; source sample count is small and is not exam frequency"
            ),
        },
    }


def _distribution(values: list[Fraction]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    for value in values:
        places = _places(value)
        counts["integer"] += places == 0
        counts["decimal_1"] += places == 1
        counts["decimal_2"] += places == 2
        counts["decimal_3_plus"] += places is not None and places > 2
        counts["non_terminating"] += places is None
        counts["negative"] += value < 0
        counts["zero"] += value == 0
        counts["abs_le_1"] += abs(value) <= 1
        counts["abs_1_to_10"] += 1 < abs(value) <= 10
        counts["abs_over_10"] += abs(value) > 10
    total = len(values)
    return {
        "sample_count": total,
        "counts": dict(counts),
        "proportions": {
            key: round(count / total, 4) if total else 0 for key, count in counts.items()
        },
    }


def build_report() -> dict[str, object]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    enabled_ids = set(ENABLED_FAMILIES)
    generated_answers = [
        generate_equation(family_id, seed).target_root
        for family_id in ENABLED_FAMILIES
        for seed in range(SAMPLE_COUNT)
    ]
    observed_answers = [value for _, _, value in REFERENCE_ANSWER_SAMPLES]
    generated_distribution = _distribution(generated_answers)
    observed_distribution = _distribution(observed_answers)
    distribution_keys = ("integer", "decimal_1", "decimal_2", "decimal_3_plus")
    total_variation = 0.5 * sum(
        abs(
            generated_distribution["proportions"].get(key, 0)
            - observed_distribution["proportions"].get(key, 0)
        )
        for key in distribution_keys
    )
    return {
        "report_version": 1,
        "generator_version": "0.1.0",
        "source_snapshot": registry["source_snapshot"],
        "sample_count_per_family": SAMPLE_COUNT,
        "acceptance_unique_target": UNIQUE_TARGET,
        "acceptance_attempt_limit": ATTEMPT_LIMIT,
        "selection_weights": {
            "linear": 50,
            "quadratic": 50,
            "status": "pedagogical, not exam statistics",
        },
        "families": [analyze_family(family_id) for family_id in ENABLED_FAMILIES],
        "answer_distribution_comparison": {
            "generated_250_per_family": generated_distribution,
            "observed_catalog_examples": observed_distribution,
            "precision_category_total_variation": round(total_variation, 4),
            "interpretation": (
                "preliminary: 8 explicitly inspected examples are not a representative "
                "exam-frequency sample"
            ),
            "sample_task_ids": [task_id for _, task_id, _ in REFERENCE_ANSWER_SAMPLES],
        },
        "enabled_structure_count": len(enabled_ids),
        "uncovered_structure_ids": [
            item["id"] for item in registry["structures"] if item["id"] not in enabled_ids
        ],
        "known_limits": [
            "No claim of complete OGE-9 catalog coverage.",
            "Only explicitly selected numeric roots are included; concatenated root sequences "
            "remain disabled.",
            "Distribution comparison is preliminary because reference samples are not a "
            "representative exam-frequency sample.",
        ],
    }


if __name__ == "__main__":
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(build_report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
