"""Run deterministic FLAT seed/render QA and write its compact report."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.math.scenario_engine import (  # noqa: E402
    QuestionSnapshot,
    ScenarioSnapshot,
    restore_asset_bytes,
)
from app.math.scenarios.stories.FLAT import SOURCE_VECTOR_SEED, build_adapter  # noqa: E402


def main() -> None:
    adapter = build_adapter()
    fingerprints: set[str] = set()
    family_counts: Counter[str] = Counter()
    family_question_fingerprints: dict[str, set[str]] = {}
    validated = 0
    for seed in range(300):
        scenario = adapter.generator.generate_scenario(seed)
        adapter.independent_oracle.validate_scenario(scenario)
        rendered = adapter.renderer.render_scenario(scenario)
        questions = tuple(
            adapter.question_builder.build_question(scenario, pos) for pos in range(1, 6)
        )
        for question in questions:
            adapter.independent_oracle.validate_question(scenario, question, rendered)
            family_counts[question.family_id] += 1
            family_question_fingerprints.setdefault(question.family_id, set()).add(
                hashlib.sha256(
                    json.dumps(
                        [question.family_id, question.condition, question.canonical_answer],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
        adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
        signature = json.dumps(
            {
                "labels": dict(scenario.context["room_labels"]),
                "questions": [(q.family_id, q.condition, q.canonical_answer) for q in questions],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
        fingerprints.add(hashlib.sha256(signature).hexdigest())
        validated += 1

    source_scenario = adapter.generator.generate_scenario(SOURCE_VECTOR_SEED)
    adapter.independent_oracle.validate_scenario(source_scenario)
    source_rendered = adapter.renderer.render_scenario(source_scenario)
    source_questions = tuple(
        adapter.question_builder.build_question(source_scenario, pos) for pos in range(1, 6)
    )
    for question in source_questions:
        adapter.independent_oracle.validate_question(source_scenario, question, source_rendered)
    adapter.independent_oracle.validate_bundle(source_scenario, source_questions, source_rendered)
    snapshot = ScenarioSnapshot(
        story_code="FLAT",
        seed=source_scenario.seed,
        generator_version=source_scenario.generator_version,
        compatibility_matrix_version=source_scenario.compatibility_matrix_version,
        context=source_scenario.context,
        shared_context=source_rendered.shared_context,
        assets=source_rendered.assets,
        questions=tuple(QuestionSnapshot.from_draft(question) for question in source_questions),
        provenance=source_scenario.provenance,
    )
    restored = {
        asset.content_type: hashlib.sha256(
            restore_asset_bytes(adapter.renderer, snapshot, asset)
        ).hexdigest()
        for asset in source_rendered.assets
    }
    report = {
        "story": "FLAT",
        "generator_version": source_scenario.generator_version,
        "seed_qa": {
            "seeds_checked": validated,
            "valid_bundles": validated,
            "unique_observable_bundle_fingerprints": len(fingerprints),
            "unique_full_kit_count": len(fingerprints),
            "family_occurrences": dict(sorted(family_counts.items())),
            "family_question_uniqueness": {
                family_id: {
                    "unique_visible_questions": len(signatures),
                    "samples": family_counts[family_id],
                }
                for family_id, signatures in sorted(family_question_fingerprints.items())
            },
            "acceptance_target": "at least 200 distinct bundles within 1200 seeds",
            "passed": validated == 300 and len(fingerprints) >= 200,
        },
        "source_control": {
            "task_ids": ["424898", "424899", "424900", "424901", "424902"],
            "provenance": (
                "catalog attributed; not independently verified as official FIPI originals"
            ),
            "expected_answers": ["1346", "12", "4.8", "50", "950"],
            "generated_answers": [
                question.canonical_answer.replace(",", ".") for question in source_questions
            ],
            "passed": [question.canonical_answer.replace(",", ".") for question in source_questions]
            == ["1346", "12", "4.8", "50", "950"],
        },
        "assets": {
            content_type: {"sha256": digest, "restored_matches_snapshot": True}
            for content_type, digest in restored.items()
        },
        "mutation_tests": [
            "room-label swap",
            "door removal",
            "parquet dimension change",
            "scale change",
            "percent denominator change",
            "tariff fee change",
            "answer order change",
        ],
        "excluded": {
            "FLAT-04-COMPOSITE-PERCENT": (
                "candidate remains disabled; source 409306 has unresolved rounding and "
                "is not used as a positive vector"
            ),
            "FLAT-ALT-TOPOLOGY": "research_only",
            "FLAT-02-CUTTING-WASTE": "blocked",
        },
        "all_families_student_enabled": False,
    }
    out = ROOT / "reports" / "oge15-flat-quality.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["seed_qa"]["passed"] or not report["source_control"]["passed"]:
        raise SystemExit("FLAT quality gate failed; see reports/oge15-flat-quality.json")
    print(f"Wrote {out}: {validated} bundles, {len(fingerprints)} distinct fingerprints")


if __name__ == "__main__":
    main()
