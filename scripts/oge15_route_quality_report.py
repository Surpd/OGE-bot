"""Run ROUTE seed/oracle QA and write a reproducible per-position report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from sys import path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "reports" / "oge15-route-quality.json"


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def _question_fingerprint(question: Any) -> str:
    """Fingerprint only a question's visible condition and its oracle inputs."""
    return json.dumps(
        {
            "family_id": question.family_id,
            "condition": question.condition,
            "math_model": _plain(question.math_model),
            "answer": question.canonical_answer,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


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
        for index, question in enumerate(questions):
            fingerprints[index].add(_question_fingerprint(question))
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
        "fingerprint_scope": (
            "family, visible condition, question-specific math model, and answer; "
            "excludes unrelated scene state"
        ),
        "natural_limits": {
            "ROUTE-F01-GRID-MATCH": (
                "bounded by visible node labels/names and their order"
            ),
            "ROUTE-F03-ROAD-SUM": (
                "bounded by two highway segment lengths and endpoint names"
            ),
            "ROUTE-F05-PYTHAGORAS": (
                "bounded by two leg lengths and endpoint names"
            ),
            "ROUTE-F06-HIGHWAY-TIME": (
                "bounded by route length, source-backed speed, and endpoint names"
            ),
            "ROUTE-F09-SHOPPING-MIN": (
                "bounded by visible basket quantities, store totals, and minimum"
            ),
        },
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
