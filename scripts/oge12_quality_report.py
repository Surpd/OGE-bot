from __future__ import annotations

import json
import random
from collections import Counter
from fractions import Fraction
from pathlib import Path

from app.math.formulas import (
    ALL_FAMILIES,
    ENABLED_FAMILIES,
    GENERATOR_VERSION,
    POLICY,
    generate,
    solve_rendered_condition,
    validate_rendered_problem,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_SEED = 20261101
SAMPLE_COUNT = 250
UNIQUE_TARGET = 200
ATTEMPT_LIMIT = 1200


def _decimal_places(value: Fraction) -> int | None:
    denominator = value.denominator
    for places in range(11):
        if denominator == 1:
            return places
        if denominator % 2 == 0:
            denominator //= 2
        elif denominator % 5 == 0:
            denominator //= 5
        else:
            return None
    return None


def _answer_fraction(raw: str) -> Fraction:
    value = POLICY.parse(raw)
    if value is None:
        raise ValueError(f"Answer is outside the task-12 numeric policy: {raw}")
    return value


def _format_oracle(family_id: str, condition: str) -> str:
    value = solve_rendered_condition(family_id, condition)
    if value is None:
        raise ValueError(f"Rendered oracle failed for {family_id}")
    return POLICY.format(value)


def main() -> None:
    structures = json.loads(
        (ROOT / "atlas/oge12_reference_structures.json").read_text(encoding="utf-8")
    )
    wording = json.loads((ROOT / "atlas/oge12_wording_patterns.json").read_text(encoding="utf-8"))
    fixtures = {item["family_id"]: item for item in wording["patterns"]}
    refs = {item["id"]: item for item in structures["families"]}
    rows = []
    for family_id in ALL_FAMILIES:
        rng = random.Random(f"oge12-report:{REPORT_SEED}:{family_id}")
        samples = [generate(family_id, rng.randrange(2**63)) for _ in range(SAMPLE_COUNT)]
        answers = [_answer_fraction(item.correct_answer) for item in samples]
        answer_places = Counter(str(_decimal_places(value)) for value in answers)
        signs = Counter(
            "negative" if value < 0 else "zero" if value == 0 else "positive" for value in answers
        )
        displayed_failures = sum(
            solve_rendered_condition(family_id, item.condition) != value
            for item, value in zip(samples, answers, strict=True)
        )
        render_failures = sum(not validate_rendered_problem(item) for item in samples)
        duplicate_rejections = SAMPLE_COUNT - len({item.fingerprint for item in samples})
        acceptance_attempts = None
        unique_count = len({item.fingerprint for item in samples})
        if family_id in ENABLED_FAMILIES:
            accept_rng = random.Random(f"oge12-acceptance:{REPORT_SEED}:{family_id}")
            seen: set[str] = set()
            acceptance_attempts = 0
            while len(seen) < UNIQUE_TARGET and acceptance_attempts < ATTEMPT_LIMIT:
                item = generate(family_id, accept_rng.randrange(2**63))
                acceptance_attempts += 1
                seen.add(item.fingerprint)
            unique_count = len(seen)
        examples = (
            [
                {
                    "problem_id": item.problem_id,
                    "seed": item.seed,
                    "condition": item.condition,
                    "answer": item.correct_answer,
                    "formula": item.formula,
                    "target": item.target,
                    "units": item.units,
                    "fingerprint": item.fingerprint,
                    "provenance": "generated_analogue_not_original_exam_task",
                }
                for item in samples[:2]
            ]
            if family_id in ENABLED_FAMILIES
            else []
        )
        row = {
            "family_id": family_id,
            "name": refs[family_id]["name"],
            "implementation_status": refs[family_id]["implementation_status"],
            "implementation_reason": refs[family_id]["implementation_reason"],
            "source_ids": [str(value) for value in refs[family_id].get("ids", [])],
            "source_status": refs[family_id].get("source_status"),
            "source_note": refs[family_id].get("note"),
            "provenance_policy": (
                "Generated examples are algorithmic analogues; "
                "source IDs identify structural references, "
                "not the generated condition as an original published task."
            ),
            "sample_count": SAMPLE_COUNT,
            "acceptance_attempts": acceptance_attempts,
            "unique_fingerprints": unique_count,
            "duplicate_rejections": duplicate_rejections,
            "math_oracle_failures": displayed_failures,
            "rendered_oracle_failures": render_failures,
            "answer_policy_failures": sum(
                POLICY.parse(item.correct_answer) is None for item in samples
            ),
            "answer_decimal_places": dict(answer_places),
            "answer_signs": dict(signs),
            "answer_frequency": dict(Counter(str(value) for value in answers)),
            "unique_condition_count": len({item.condition for item in samples}),
            "unique_parameter_set_count": len(
                {tuple(sorted(item.variables.items())) for item in samples}
            ),
            "unique_correct_answer_count": len(set(answers)),
            "r005_sine_values": (
                sorted({str(value) for value in answers}) if family_id == "OGE12-R005" else None
            ),
            "answer_min": str(min(answers)),
            "answer_max": str(max(answers)),
            "authored_fixture": {
                "source_task_id": str(fixtures[family_id]["origin_task_id"]),
                "provenance": "authored_research_example_not_verbatim",
                "condition": fixtures[family_id]["authored_ready_to_use_condition"],
                "expected_answer": fixtures[family_id]["correct_answer"],
                "oracle_answer": _format_oracle(
                    family_id, fixtures[family_id]["authored_ready_to_use_condition"]
                ),
            },
            "examples": examples,
        }
        rows.append(row)
    report = {
        "generator_version": GENERATOR_VERSION,
        "report_seed": REPORT_SEED,
        "sample_count_per_family": SAMPLE_COUNT,
        "unique_target": UNIQUE_TARGET,
        "attempt_limit": ATTEMPT_LIMIT,
        "enabled_family_ids": list(ENABLED_FAMILIES),
        "disabled_family_ids": [item for item in ALL_FAMILIES if item not in ENABLED_FAMILIES],
        "source_registry_version": structures["schema_version"],
        "oracle_note": "Rendered conditions, both sides of formula signatures, exact coefficients, units, target variables, numeric givens, metadata, and every derivation step are checked independently from generator values; authored research examples are checked against the same family oracle.",  # noqa: E501
        "oracle_mutation_regressions": [
            "R005: change the displayed denominator /2 to /3",
            "R011: change displayed g = 9.8 to g = 19.8",
            "R012: change displayed rho = 1000 to rho = 21000",
            "R001-R017: mutate formula coefficients, units, or target variable",
            "R001-R017: mutate the left side of the displayed formula",
            "R001-R017: mutate each derivation step, exact answer, and formula metadata",
        ],
        "trigonometry_policy": {
            "R005_generated_sine_values": (
                "exact tenths in (0, 1], from the area formula; "
                "source-task answer 0.4 is confirmed"
            ),
            "R016_generated_angles_degrees": [30, 90, 150],
            "note": (
                "R005 asks to recover sin(alpha), not evaluate a named angle; R016 uses "
                "standard-angle values. The broader R005 response distribution remains "
                "preliminary because only one exact source answer was cross-checked."
            ),
        },
        "families": rows,
        "overall": {
            "family_count": len(rows),
            "enabled_family_count": len(ENABLED_FAMILIES),
            "disabled_family_count": len(ALL_FAMILIES) - len(ENABLED_FAMILIES),
            "sample_count": SAMPLE_COUNT * len(rows),
            "math_oracle_failures": sum(item["math_oracle_failures"] for item in rows),
            "rendered_oracle_failures": sum(item["rendered_oracle_failures"] for item in rows),
            "authored_fixture_count": len(fixtures),
            "authored_fixture_oracle_failures": sum(
                POLICY.parse(item["authored_fixture"]["expected_answer"])
                != POLICY.parse(item["authored_fixture"]["oracle_answer"])
                for item in rows
            ),
        },
    }
    output = ROOT / "reports/oge12-quality.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["overall"], ensure_ascii=False))


if __name__ == "__main__":
    main()
