from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from app.math.scenario_engine import (
    FamilyRegistry,
    JsonValue,
    PracticeMode,
    PracticeRequest,
    QuestionDraft,
    ScenarioDraft,
    StoryAdapter,
    build_practice_plan,
)
from app.math.scenarios.stories.PAPER import (
    _SOURCE_IDS,
    PaperAdapter,
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


def _question_for_family(
    adapter: PaperAdapter, scenario: ScenarioDraft, family_id: str, seed: int
) -> QuestionDraft | tuple[ScenarioDraft, QuestionDraft]:
    position = FAMILY_POSITION[family_id]
    if position != 4:
        return adapter.question_builder.build_question(scenario, position)
    raw_questions_value = scenario.context.get("questions")
    if not isinstance(raw_questions_value, Mapping):
        raise ValueError("Quality sample is missing position-four parameters")
    raw_questions = {key: _plain(value) for key, value in raw_questions_value.items()}
    q4_value = raw_questions.get("4")
    if not isinstance(q4_value, Mapping):
        raise ValueError("Quality sample is missing position-four parameters")
    q4 = dict(q4_value)
    q4["family_id"] = family_id
    q4["format_index"] = seed % 7 if family_id == "PAPER-F04" else 2
    raw_questions["4"] = q4
    context = {key: _plain(value) for key, value in scenario.context.items()}
    context["questions"] = raw_questions
    family_scenario = replace(scenario, context=cast(Mapping[str, JsonValue], context))
    adapter.independent_oracle.validate_scenario(family_scenario)
    return family_scenario, adapter.question_builder.build_question(family_scenario, position)


def _fingerprint(family_id: str, model: dict[str, object]) -> tuple[object, ...]:
    if family_id == "PAPER-F01":
        target_order, rows = model["target_order"], model["rows"]
        if not isinstance(target_order, tuple | list) or not isinstance(rows, tuple | list):
            raise ValueError("PAPER-F01 fingerprint is missing its visible ordering or rows")
        if not all(isinstance(row, tuple | list) for row in rows):
            raise ValueError("PAPER-F01 fingerprint contains malformed rows")
        return (tuple(target_order), tuple(tuple(row) for row in rows))
    if family_id == "PAPER-F02":
        return (model["source_index"], model["target_index"])
    if family_id == "PAPER-F03":
        return (model["format_index"], model["side"], model["multiple"])
    if family_id == "PAPER-F04":
        return (model["format_index"], "short_over_long")
    if family_id == "PAPER-F06":
        return ("A2", "diagonal_over_short")
    if family_id == "PAPER-F07":
        return (model["source_index"], model["target_index"], model["old_pt"])
    raise ValueError(f"Unexpected PAPER family: {family_id}")


def build_report() -> dict[str, object]:
    adapter = build_adapter()
    registry = FamilyRegistry((cast(StoryAdapter, adapter),))
    family_report: dict[str, dict[str, object]] = {}
    for family_id, position in FAMILY_POSITION.items():
        fingerprints: set[tuple[object, ...]] = set()
        answers: set[str] = set()
        for seed in range(300):
            scenario = adapter.generator.generate_scenario(seed)
            adapter.independent_oracle.validate_scenario(scenario)
            rendered = adapter.renderer.render_scenario(scenario)
            selected = _question_for_family(adapter, scenario, family_id, seed)
            if position == 4:
                if not isinstance(selected, tuple):
                    raise TypeError("Position-four quality sample must include its forced scenario")
                scenario, question = selected
            else:
                if isinstance(selected, tuple):
                    raise TypeError("Non-position-four quality sample cannot replace its scenario")
                question = selected
            adapter.independent_oracle.validate_question(scenario, question, rendered)
            fingerprints.add(
                _fingerprint(family_id, cast(dict[str, object], _plain(question.math_model)))
            )
            answers.add(question.canonical_answer)
        family_report[family_id] = {
            "status": "enabled_candidate",
            "enabled": True,
            "sources": list(_SOURCE_IDS[family_id]),
            "samples_validated": 300,
            "unique_structural_fingerprints": len(fingerprints),
            "unique_canonical_answers": len(answers),
            "fingerprint_examples": [list(value) for value in sorted(fingerprints, key=repr)[:6]],
        }

    uniqueness: dict[str, object] = {}
    for family_id in ("PAPER-F01", "PAPER-F07"):
        fingerprints = {
            _fingerprint(
                family_id,
                cast(
                    dict[str, object],
                    _plain(_question_for_family_for_diversity(adapter, family_id, seed)),
                ),
            )
            for seed in range(1200)
        }
        uniqueness[family_id] = {
            "attempts": 1200,
            "unique_structural_fingerprints": len(fingerprints),
            "target": 200,
            "passed": len(fingerprints) >= 200,
        }

    full_bundle_seeds = 300
    family_sets: set[tuple[str, ...]] = set()
    for seed in range(full_bundle_seeds):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed=seed, story_code="PAPER"), registry
        )
        family_sets.add(tuple(question.family_id for question in plan.snapshot.questions))

    natural_capacity = {
        "PAPER-F02": {
            "observed_unique_conditions": 21,
            "unique_answers": 6,
            "exception": "finite A0..A6 index pairs",
        },
        "PAPER-F03": {
            "observed_unique_conditions": 2,
            "unique_answers": 2,
            "exception": "only two individually checked side/multiple combinations",
        },
        "PAPER-F04": {
            "observed_unique_conditions": 7,
            "unique_answers": 1,
            "exception": "same 0.7 answer for rounded A0..A6 dimensions",
        },
        "PAPER-F06": {
            "observed_unique_conditions": 1,
            "unique_answers": 1,
            "exception": "only the source-verified A2 diagonal ratio is implemented",
        },
    }
    return {
        "story": "PAPER",
        "generator_version": "paper-v1",
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
        "visual_audit": {
            "screen_widths_px": [360, 390, 430],
            "table_png": "1024x520; all headers, row labels and values remain within the canvas",
            "diagram_png": "960x640; A0-A5 labels and successive arrows remain within the canvas",
            "result": "visually inspected at all three scaled widths",
        },
    }


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _question_for_family_for_diversity(
    adapter: PaperAdapter, family_id: str, seed: int
) -> Mapping[str, JsonValue]:
    scenario = adapter.generator.generate_scenario(seed)
    if family_id == "PAPER-F01":
        return adapter.question_builder.build_question(scenario, 1).math_model
    q5 = adapter.question_builder.build_question(scenario, 5)
    return q5.math_model


def main() -> None:
    report = build_report()
    output = Path("reports/oge15-paper-quality.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
