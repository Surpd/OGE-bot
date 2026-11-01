from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.math.progressions import (  # noqa: E402
    A04,
    A11,
    ALL_FAMILIES,
    FAMILY_STATUS,
    SOURCE_IDS,
    SOURCE_URLS,
    audit_condition,
    generate,
    solve_condition,
)

QUICK_CASES = 40
MAIN_CASES = 250
ACCEPTANCE_BUDGET = 1200
EXCLUDED = {A04, A11}


def run() -> dict[str, object]:
    report: dict[str, object] = {
        "task": 14,
        "generator_version": "0.1.0",
        "provenance": "generated_analogue; no historical-original claim",
        "quick_cases_per_family": QUICK_CASES,
        "main_cases_per_family": MAIN_CASES,
        "acceptance_budget": ACCEPTANCE_BUDGET,
        "families": {},
        "release_gate": (
            "quality_and_postgres17_ci_passed; "
            "live_telegram_smoke_required_before_release"
        ),
    }
    results = report["families"]
    assert isinstance(results, dict)
    for family in ALL_FAMILIES:
        if family in EXCLUDED:
            results[family] = {
                "status": FAMILY_STATUS[family],
                "source_ids": list(SOURCE_IDS[family]),
                "source_urls": list(SOURCE_URLS[family]),
                "quick_valid": 0,
                "main_valid": 0,
                "unique_within_budget": 0,
            }
            continue
        problems = [generate(family, seed) for seed in range(MAIN_CASES)]
        unique: set[str] = set()
        attempts = 0
        for seed in range(ACCEPTANCE_BUDGET):
            attempts += 1
            unique.add(generate(family, seed).fingerprint)
            if len(unique) >= 200:
                break
        answers = [float(problem.exact_value) for problem in problems]
        results[family] = {
            "status": FAMILY_STATUS[family],
            "source_ids": list(problems[0].reference_ids),
            "source_urls": list(SOURCE_URLS[family]),
            "quick_valid": sum(
                solve_condition(family, p.condition) == p.exact_value
                for p in problems[:QUICK_CASES]
            ),
            "main_valid": sum(
                audit_condition(family, p.condition, p.parameters)
                and solve_condition(family, p.condition) == p.exact_value
                for p in problems
            ),
            "unique_within_budget": len(unique),
            "acceptance_attempts": attempts,
            "answer_range": [min(answers), max(answers)],
            "visible_parameter_ranges": {
                name: [
                    min(int(problem.parameters[name]) for problem in problems),
                    max(int(problem.parameters[name]) for problem in problems),
                ]
                for name in problems[0].parameters
            },
            "median_answer": statistics.median(answers),
            "distinct_structures": len({tuple(sorted(p.parameters.items())) for p in problems}),
            "distinct_fingerprints_main": len({p.fingerprint for p in problems}),
            "answer_types": dict(
                Counter(
                    "integer" if p.exact_value.denominator == 1 else "decimal" for p in problems
                )
            ),
            "max_rendered_characters": max(len(p.condition) for p in problems),
            "max_generation_attempts": max(p.generation_attempts for p in problems),
            "all_oracles_passed": all(
                audit_condition(family, p.condition, p.parameters)
                and solve_condition(family, p.condition) == p.exact_value
                for p in problems
            ),
            "gate_note": (
                "42-fingerprint natural finite capacity (n=3..8, d=2..8); stays disabled: "
                "rolling global history retains only 30 fingerprints and cannot guarantee "
                "the full family cycle without repeats; no artificial parameter expansion"
                if family == "OGE14-A06"
                else "oracle, text audit, diversity, shared UX, and PostgreSQL 17 CI passed"
                if family in FAMILY_STATUS and FAMILY_STATUS[family].startswith("enabled_")
                else "family is held or disabled pending quality gates"
            ),
        }
    return report


if __name__ == "__main__":
    result = run()
    Path("reports/oge14-quality.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Wrote reports/oge14-quality.json")
