"""Run the GARDEN adapter's 250-seed source and snapshot quality gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.math.scenario_engine import (  # noqa: E402
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.recent_questions import question_signature  # noqa: E402
from app.math.scenarios.stories.GARDEN import FAMILIES, VERSION, build_adapter  # noqa: E402


def main() -> int:
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    registry = FamilyRegistry((adapter,))
    fingerprints: set[tuple[object, ...]] = set()
    answers: dict[str, set[str]] = {family: set() for family in FAMILIES}
    failures: list[str] = []
    samples = 250
    source_answers: list[str] = []
    for seed in range(samples):
        try:
            plan = build_practice_plan(PracticeRequest(PracticeMode.FULL, seed, "GARDEN"), registry)
            snapshot = plan.snapshot
            fingerprints.add(tuple(question_signature(snapshot, q) for q in snapshot.questions))
            if seed < 100:
                for question in snapshot.questions:
                    answers[question.family_id].add(question.canonical_answer)
            if seed == 0:
                source_answers = [q.canonical_answer for q in snapshot.questions]
                if source_answers != ["7425", "7", "36", "29", "500"]:
                    raise ValueError("source answers have changed")
            if tuple(q.family_id for q in snapshot.questions) != FAMILIES:
                raise ValueError("wrong ordered family block")
            for asset in plan.snapshot.assets:
                restored = restore_asset_bytes(adapter.renderer, plan.snapshot, asset)
                if not restored.startswith(b"<svg"):
                    raise ValueError("asset is not SVG")
        except Exception as exc:  # report each seed without hiding later failures
            failures.append(f"seed={seed}: {type(exc).__name__}: {exc}")
    diversity = {family: len(values) for family, values in answers.items()}
    sufficient_geometry = all(diversity[family] >= 10 for family in FAMILIES[1:4])
    result = {
        "story": "GARDEN",
        "generator_version": VERSION,
        "samples": samples,
        "failures": failures,
        "unique_full_input_signatures": len(fingerprints),
        "distinct_answers_first_100_seeds": diversity,
        "target_unique": 200,
        "source_fixture_seed_0_answers": source_answers,
        "passed": not failures and len(fingerprints) >= 200 and sufficient_geometry,
        "enabled_families": list(FAMILIES),
        "disabled_families": [f.family_id for f in adapter.family_registry if not f.enabled],
    }
    report = ROOT / "reports/oge15-garden-quality.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
