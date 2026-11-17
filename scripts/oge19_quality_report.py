"""Run a deterministic QA sample for the OGE19 claim bank and triple builder."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.math.oge19 import (
    ANSWER_POLICY_ID,
    ANSWER_POLICY_VERSION,
    EXAM_FORMAT,
    GENERATOR_VERSION,
    STATEMENTS,
    check_answer,
    generate,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def build_report(samples: int = 500, unique_target: int = 200) -> dict[str, object]:
    if samples < 1 or unique_target < 1:
        raise ValueError("samples and unique_target must be positive")
    masks: Counter[str] = Counter()
    positions: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    fingerprints: set[tuple[str, ...]] = set()
    failed_answers = 0
    for seed in range(samples):
        triple = generate(seed)
        snapshot = triple.snapshot()
        validate_snapshot(snapshot)
        masks[triple.answer_mask] += 1
        positions[triple.answer_mask] += 1
        topics.update(item.topic for item in triple.statements)
        fingerprints.add(tuple(sorted(item.proposition_id for item in triple.statements)))
        if not check_answer(snapshot, triple.answer_mask):
            failed_answers += 1
    if failed_answers or len(fingerprints) < unique_target:
        raise RuntimeError(
            f"QA gate failed: {failed_answers} answer errors, "
            f"{len(fingerprints)} unique triples (<{unique_target})"
        )
    matrix = json.loads((ROOT / "specs/research/oge19/SOURCE_MATRIX.json").read_text())
    return {
        "task_number": 19,
        "exam_format": EXAM_FORMAT,
        "fipi_format_source": (
            "https://doc.fipi.ru/oge/demoversii-specifikacii-kodifikatory/2027/ma_9_2027.zip"
        ),
        "fipi_checked_on": "2026-11-17",
        "generator_version": GENERATOR_VERSION,
        "answer_policy_id": ANSWER_POLICY_ID,
        "answer_policy_version": ANSWER_POLICY_VERSION,
        "bank_version": "oge19-claims-1",
        "source_prototypes": matrix["source_count"],
        "statement_count": len(STATEMENTS),
        "samples": samples,
        "unique_triples": len(fingerprints),
        "unique_target": unique_target,
        "answer_mask_counts": dict(sorted(masks.items())),
        "correct_position_counts": dict(sorted(positions.items())),
        "topic_appearances": dict(sorted(topics.items())),
        "answer_errors": failed_answers,
        "snapshot_checks": samples,
        "result": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--unique-target", type=int, default=200)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/oge19-quality.json")
    args = parser.parse_args()
    report = build_report(args.samples, args.unique_target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
