"""Run ROUTE seed/oracle QA and write a reproducible per-position report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from sys import path

ROOT = Path(__file__).resolve().parents[1]
path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "reports" / "oge15-route-quality.json"


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def build_report(seed_count: int) -> dict[str, object]:
    from app.math.scenarios.stories.ROUTE import build_adapter

    adapter = build_adapter()
    oracle = adapter.independent_oracle
    fingerprints = [set[str]() for _ in range(5)]
    for seed in range(seed_count):
        scenario = adapter.generator.generate_scenario(seed + 1)
        oracle.validate_scenario(scenario)
        rendered = adapter.renderer.render_scenario(scenario)
        questions = tuple(adapter.question_builder.build_question(scenario, p) for p in range(1, 6))
        oracle.validate_bundle(scenario, questions, rendered)
        scene = json.dumps(_plain(scenario.context), ensure_ascii=False, sort_keys=True)
        for index, question in enumerate(questions):
            fingerprint = json.dumps(
                {
                    "scene": scene,
                    "family_id": question.family_id,
                    "condition": question.condition,
                    "math_model": _plain(question.math_model),
                    "answer": question.canonical_answer,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            fingerprints[index].add(fingerprint)
    return {
        "story_code": "ROUTE",
        "generator_version": "route-grid4-v1",
        "compatibility_matrix_version": "route-grid4-bundle-v1",
        "seed_count": seed_count,
        "seed_range": [1, seed_count],
        "oracle_passes": seed_count * 5,
        "renderer_formats": ["image/svg+xml", "image/png"],
        "family_quality": [
            {
                "family_id": registration.family_id,
                "position": registration.position,
                "status": str(registration.status),
                "enabled": registration.enabled,
                "attempts": seed_count,
                "unique_fingerprints": len(fingerprints[registration.position - 1]),
                "acceptance_minimum": 200,
                "acceptance_budget": 1200,
            }
            for registration in adapter.family_registry
        ],
        "all_acceptance_thresholds_met": all(len(group) >= 200 for group in fingerprints),
        "student_enabled": False,
        "visual_source_audit": (
            "pending; original source images were unavailable in the research archive"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=1200)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error("--seeds must be positive")
    report = build_report(args.seeds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_acceptance_thresholds_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
