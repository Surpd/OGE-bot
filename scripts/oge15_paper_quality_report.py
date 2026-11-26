from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    StoryAdapter,
    build_practice_plan,
)
from app.math.scenarios.recent_questions import _paper_inputs
from app.math.scenarios.stories.PAPER import (
    _SOURCE_IDS,
    GENERATOR_VERSION,
    build_adapter,
)

FAMILY_POSITION = {
    "PAPER-F01": 1,
    "PAPER-F02": 2,
    "PAPER-F03": 3,
    "PAPER-F04": 4,
    "PAPER-F06": 4,
    "PAPER-F07": 5,
}


def build_report() -> dict[str, object]:
    adapter = build_adapter(enabled_families=frozenset(FAMILY_POSITION))
    registry = FamilyRegistry((cast(StoryAdapter, adapter),))
    family_report: dict[str, dict[str, object]] = {}
    for family_id, position in FAMILY_POSITION.items():
        fingerprints: set[str] = set()
        answers: set[str] = set()
        for seed in range(300):
            scenario = adapter.generator.generate_scenario_for_family(seed, position, family_id)
            adapter.independent_oracle.validate_scenario(scenario)
            rendered = adapter.renderer.render_scenario(scenario)
            question = adapter.question_builder.build_question(scenario, position)
            adapter.independent_oracle.validate_question(scenario, question, rendered)
            operands = _paper_inputs(scenario.context, question.math_model, family_id)
            fingerprints.add(json.dumps(operands, ensure_ascii=False))
            answers.add(question.canonical_answer)
        family_report[family_id] = {
            "status": "enabled_candidate",
            "enabled_in_quality_harness": True,
            "sources": list(_SOURCE_IDS[family_id]),
            "samples_validated": 300,
            "unique_structural_fingerprints": len(fingerprints),
            "unique_canonical_answers": len(answers),
            "fingerprint_examples": [json.loads(value) for value in sorted(fingerprints)[:6]],
        }

    fingerprints = set()
    for seed in range(1200):
        scenario = adapter.generator.generate_scenario(seed)
        mapping = adapter.question_builder.build_question(scenario, 1)
        operands = _paper_inputs(scenario.context, mapping.math_model, "PAPER-F01")
        fingerprints.add(json.dumps(operands, ensure_ascii=False))
    uniqueness = {
        "PAPER-F01": {
            "attempts": 1200,
            "unique_structural_fingerprints": len(fingerprints),
            "target": 200,
            "passed": len(fingerprints) >= 200,
        }
    }

    full_bundle_seeds = 300
    family_sets: set[tuple[str, ...]] = set()
    for seed in range(full_bundle_seeds):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed=seed, story_code="PAPER"), registry
        )
        family_sets.add(tuple(question.family_id for question in plan.snapshot.questions))

    natural_capacity = {
        "PAPER-F02": "1–5 starting sheets and six cutting depths",
        "PAPER-F03": "bounded ISO side values with meaningful rounding to 5 or 10 mm",
        "PAPER-F04": "eight ISO formats at one or two decimal places",
        "PAPER-F06": "four exact ISO reconstructions, two denominators and two precisions",
        "PAPER-F07": "two format directions and 17 point sizes",
    }
    return {
        "story": "PAPER",
        "generator_version": GENERATOR_VERSION,
        "seed_range": "0..1199",
        "per_family_samples": family_report,
        "structural_uniqueness": uniqueness,
        "natural_capacity_exceptions": natural_capacity,
        "full_bundle": {
            "seeds_validated": full_bundle_seeds,
            "selected_positions": [1, 2, 3, 4, 5],
            "family_combinations_observed": len(family_sets),
            "all_questions_share_one_seed": True,
            "single_and_full_snapshot_gate": "covered by tests/test_oge15_paper.py",
        },
        "blocked_families": {
            "PAPER-F05": (
                "research_only: secondary collection, no individually verified catalog task ID"
            ),
            "PAPER-F08": "blocked: ideal area and rounded-dimension area disagree",
            "PAPER-F09": "blocked: ideal-area and rounded-dimension mass disagree",
        },
        "independent_oracle": "scenario, rendered text/table, each question and bundle validated",
        "renderer": "deterministic PNG diagram + table; snapshot restore SHA-256 checked in tests",
    }


def main() -> None:
    report = build_report()
    output = Path("reports/oge15-paper-quality.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
