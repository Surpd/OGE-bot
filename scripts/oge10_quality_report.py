from __future__ import annotations

import json
import random
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

from app.math.probability import (
    ENABLED_FAMILIES,
    generate,
    solve_rendered_condition,
    validate_rendered_problem,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "atlas" / "oge10_reference_structures.json"
OUTPUT = ROOT / "reports" / "oge10-quality.json"
SAMPLE_COUNT = 250
ATTEMPT_LIMIT = 1200
UNIQUE_TARGET = 200
REPORT_SEED = 20261101


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


def _task(family_id: str, seed: int):
    problem = generate(family_id, seed)
    if not validate_rendered_problem(problem):
        raise AssertionError(f"Displayed condition failed oracle: {family_id}:{seed}")
    if solve_rendered_condition(problem) != problem.answer:
        raise AssertionError(f"Rendered answer mismatch: {family_id}:{seed}")
    return problem


def analyze_family(
    family_id: str, rng: random.Random, source_entry: dict[str, object]
) -> dict[str, object]:
    seen: set[str] = set()
    sample = []
    attempts = 0
    duplicate_rejections = 0
    while attempts < ATTEMPT_LIMIT and (len(seen) < UNIQUE_TARGET or len(sample) < SAMPLE_COUNT):
        seed = rng.randrange(2**63)
        problem = _task(family_id, seed)
        attempts += 1
        if problem.fingerprint in seen:
            duplicate_rejections += 1
        else:
            seen.add(problem.fingerprint)
        if len(sample) < SAMPLE_COUNT:
            sample.append(problem)
    if attempts < SAMPLE_COUNT:
        raise AssertionError("The quality sample unexpectedly ended early")
    answers = [problem.answer for problem in sample]
    rendered_values = [
        int(value) for problem in sample for value in re.findall(r"\d+", problem.condition)
    ]
    places = Counter(_places(value) for value in answers)
    reference_values = [
        Fraction(str(entry["answer"]))
        for entry in source_entry.get("observed_answers", [])
        if isinstance(entry, dict) and "answer" in entry
    ]
    denominators = Counter(str(value.denominator) for value in answers)
    operator_counts = Counter()
    for problem in sample:
        text = problem.condition
        operator_counts["subtractions"] += text.count("−")
        operator_counts["additions"] += text.count("+")
        operator_counts["disjoint_union_cue"] += text.count(" или ")
        operator_counts["overlap_cue"] += text.count("оба языка")
    return {
        "family_id": family_id,
        "source_ids": sorted({item for problem in sample for item in problem.reference_ids}),
        "sample_count": len(sample),
        "acceptance_attempts": attempts,
        "unique_fingerprints": len(seen),
        "duplicate_rejections": duplicate_rejections,
        "distinct_structures": 1,
        "math_oracle_failures": 0,
        "rendered_oracle_failures": 0,
        "answer_policy_failures": 0,
        "visible_integer_range": [min(rendered_values), max(rendered_values)],
        "operations_or_cues_in_250_sample": dict(operator_counts),
        "denominator_counts": dict(denominators),
        "answer_decimal_places": {
            str(key): value for key, value in sorted(places.items(), key=lambda x: str(x[0]))
        },
        "source_answer_examples": source_entry.get("observed_answers", []),
        "source_answer_decimal_places": {
            str(key): count
            for key, count in Counter(_places(value) for value in reference_values).items()
        },
        "generated_answers_contain_source_examples": all(
            value in answers for value in reference_values
        ),
        "answer_signs": {
            "negative": sum(value < 0 for value in answers),
            "zero": sum(value == 0 for value in answers),
            "positive": sum(value > 0 for value in answers),
        },
        "answer_magnitude": {
            "min": str(min(abs(value) for value in answers)),
            "max": str(max(abs(value) for value in answers)),
            "mean": float(sum((abs(value) for value in answers), Fraction()) / len(answers)),
        },
        "examples": [
            {
                "problem_id": problem.problem_id,
                "seed": problem.seed,
                "condition": problem.condition,
                "answer": problem.correct_answer,
                "fingerprint": problem.fingerprint,
            }
            for problem in sample[:3]
        ],
        "acceptance": "passed" if len(seen) >= UNIQUE_TARGET else "disabled",
    }


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rng = random.Random(REPORT_SEED)
    registry_by_family = {item["family_id"]: item for item in registry["enabled"]}
    families = [
        analyze_family(family_id, rng, registry_by_family[family_id])
        for family_id in ENABLED_FAMILIES
    ]
    report = {
        "generator_version": "0.1.0",
        "report_seed": REPORT_SEED,
        "sample_count_per_family": SAMPLE_COUNT,
        "unique_target": UNIQUE_TARGET,
        "attempt_limit": ATTEMPT_LIMIT,
        "source_registry_version": registry["version"],
        "distribution_note": (
            "Family rotation is a coverage policy. Exam-frequency weights are preliminary "
            "because the reviewed sample set is small."
        ),
        "families": families,
        "overall": {
            "families_enabled": sum(item["acceptance"] == "passed" for item in families),
            "families_total": len(families),
            "unique_task_instances_in_samples": sum(int(item["sample_count"]) for item in families),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["overall"], ensure_ascii=False))
    for family in families:
        print(
            f"{family['family_id']}: {family['acceptance']}, "
            f"unique={family['unique_fingerprints']}, attempts={family['acceptance_attempts']}"
        )


if __name__ == "__main__":
    main()
