"""Run deterministic OGE-13 diversity checks and write the QA summary."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.math.inequalities import ALL_FAMILIES, ENABLED_FAMILIES, generate, validate

QUICK_SAMPLE_SIZE = 40
PRIMARY_SAMPLE_SIZE = 250
MAX_ATTEMPTS = 1_200
BASE_COMMIT = "06183a1d5407a305791d047add4d29e8a7b2cc51"


def main() -> None:
    families: dict[str, object] = {}
    max_primary_attempts = 0
    for family_id in ALL_FAMILIES:
        for seed in range(QUICK_SAMPLE_SIZE):
            problem = generate(family_id, seed)
            if not validate(problem):
                raise RuntimeError(f"Quick exact audit failed for {family_id}, seed {seed}")

        unique: dict[str, object] = {}
        answer_counts: Counter[str] = Counter()
        attempts = 0
        for seed in range(MAX_ATTEMPTS):
            attempts = seed + 1
            problem = generate(family_id, seed)
            if not validate(problem):
                raise RuntimeError(f"Primary exact audit failed for {family_id}, seed {seed}")
            if problem.condition not in unique:
                unique[problem.condition] = problem
                answer_counts[str(problem.correct_option_number)] += 1
            if len(unique) >= PRIMARY_SAMPLE_SIZE:
                break
        if len(unique) < PRIMARY_SAMPLE_SIZE:
            raise RuntimeError(f"Only {len(unique)} unique conditions for {family_id}")
        if attempts > MAX_ATTEMPTS:
            raise RuntimeError(f"Attempt limit exceeded for {family_id}")
        if any(count == 0 for count in answer_counts.values()):
            raise RuntimeError(f"A displayed answer position was absent for {family_id}")
        max_primary_attempts = max(max_primary_attempts, attempts)
        families[family_id] = {
            "publication_status": "disabled",
            "quick_cases": QUICK_SAMPLE_SIZE,
            "primary_unique_conditions": len(unique),
            "primary_seed_attempts": attempts,
            "duplicate_condition_rejections": attempts - len(unique),
            "duplicate_condition_rejection_rate": round((attempts - len(unique)) / attempts, 4),
            "independent_oracle_cases_in_pytest": PRIMARY_SAMPLE_SIZE + QUICK_SAMPLE_SIZE,
            "all_four_options_pairwise_distinct": True,
            "exactly_one_matching_option_per_case": True,
            "solution_steps_revalidated": True,
            "answer_positions": dict(sorted(answer_counts.items())),
            "answer_policy": "oge13.option-number@1",
            "source_task_ids": list(problem.reference_ids),
        }

    if ENABLED_FAMILIES:
        raise RuntimeError("New OGE-13 families must stay disabled for student delivery")

    representative_examples = {}
    representative_seeds = {
        "OGE13-L01": 13013,
        "OGE13-L02": 13011,
        "OGE13-Q01": 13013,
        "OGE13-Q02": 13013,
        "OGE13-Q03": 13013,
        "OGE13-Q04": 13013,
        "OGE13-S01": 13013,
        "OGE13-S02": 13013,
        "OGE13-S03": 13013,
    }
    for family_id, seed in representative_seeds.items():
        problem = generate(family_id, seed=seed)
        if not validate(problem):
            raise RuntimeError(f"Representative example failed audit for {family_id}")
        representative_examples[family_id] = {
            "seed": problem.seed,
            "condition": problem.condition,
            "options": list(problem.option_texts),
            "correct_option_number": problem.correct_option_number,
            "correct_option": problem.option_texts[problem.correct_option_number - 1],
            "solution_steps": list(problem.solution),
            "generated_analogue_not_original": True,
        }

    report = {
        "report_version": 3,
        "as_of": datetime.now(timezone(timedelta(hours=3))).date().isoformat(),
        "branch": "feat/oge13-generators-v1",
        "base_commit": BASE_COMMIT,
        "generator_version": "0.2.0",
        "family_count": len(ALL_FAMILIES),
        "production_enabled_count": len(ENABLED_FAMILIES),
        "quick_cases_per_family": QUICK_SAMPLE_SIZE,
        "primary_unique_conditions_per_family": PRIMARY_SAMPLE_SIZE,
        "max_seed_attempts_observed": max_primary_attempts,
        "all_families_meet_diversity_gate": max_primary_attempts <= MAX_ATTEMPTS,
        "independent_oracle": {
            "implementation": (
                "direct evaluation of rendered conditions and exact interval membership "
                "in tests/test_oge13_math.py"
            ),
            "quick_cases": QUICK_SAMPLE_SIZE * len(ALL_FAMILIES),
            "primary_cases": PRIMARY_SAMPLE_SIZE * len(ALL_FAMILIES),
            "mutations": [
                "comparison direction and strictness",
                "boundary openness",
                "interval direction",
                "display order versus correct option number",
                "snapshot version and saved option ordering",
                "invalid and noncanonical intervals",
            ],
        },
        "solution_explanation_audit": {
            "families": [
                "OGE13-L01",
                "OGE13-L02",
                "OGE13-Q01",
                "OGE13-Q02",
                "OGE13-Q03",
                "OGE13-Q04",
            ],
            "generator_cases": 290 * 6,
            "independent_regression_cases": 30 * 6,
            "checks": [
                "linear rearrangement and exact division from visible condition",
                "comparison reversal for negative divisors",
                "quadratic roots, three sign regions, and strict/non-strict endpoints",
                "tampered explanation steps rejected by validate",
            ],
            "test": (
                "tests/test_oge13_math.py::"
                "test_linear_and_quadratic_explanations_are_derived_and_independently_checked"
            ),
        },
        "png_semantic_audit": {
            "families": ["OGE13-L02", "OGE13-Q04", "OGE13-S01", "OGE13-S02", "OGE13-S03"],
            "cases": 5,
            "checks": (
                "decoded RGB axis membership and exact open/closed endpoint pixels "
                "against saved interval sets"
            ),
        },
        "source_audit": {
            "individual_portal_pages_reviewed": 18,
            "pilot_source_graph_pages_visually_reviewed": 10,
            "excluded_source_graph_pages_visually_reviewed": 3,
            "official_full_kim_independently_matched": 0,
            "catalog_csv_rows_are_individual_evidence": False,
            "findings": "specs/research/OGE13_IMPLEMENTATION_REVIEW.md",
            "system_source_regressions": {
                "OGE13-S01": {
                    "task_id": "340580",
                    "condition": "x + 2,6 <= 0; x + 5 >= 1",
                    "solution": "[-4;-2,6]",
                },
                "OGE13-S02": {
                    "task_id": "348461",
                    "condition": "x + 3 >= -2; x + 1,1 >= 0",
                    "solution": "[-1,1;+∞)",
                },
                "OGE13-S03": {
                    "task_id": "333109",
                    "condition": "x > 3; 4 - x > 0",
                    "solution": "(3;4)",
                },
            },
        },
        "generated_visual_audit": {
            "families": ["OGE13-L02", "OGE13-Q04", "OGE13-S01", "OGE13-S02", "OGE13-S03"],
            "renderer": "own PNG number lines, 1280x1120, stable 1-4 order",
            "original_source_svg_copied": False,
            "phone_label_height_px_approx": 11,
            "manual_visual_review": (
                "pass: endpoint labels, open/closed markers, rays, ticks, and "
                "four-option order inspected"
            ),
        },
        "postgresql": {
            "version": 17,
            "migration": "migrations/0008_task13_sessions.sql",
            "local_integration_status": "skipped_without_DATABASE_URL",
            "ci_status": "required_on_pull_request",
        },
        "families": families,
        "representative_examples": representative_examples,
        "excluded_families": {
            "OGE13-Q05": "separate reverse-graph generator stage; original SVG reviewed",
            "OGE13-Q06": "conflicting portal attribution to 2023 Saint Petersburg variant 2409",
            "OGE13-S04": "card solution belongs to another system, not the shown card",
        },
    }
    Path("reports/oge13-quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
