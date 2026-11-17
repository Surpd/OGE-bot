"""Run a deterministic QA sample for the OGE19 claim bank and triple builder."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.math.oge19 import (
    ANSWER_POLICY_ID,
    ANSWER_POLICY_VERSION,
    BANK_VERSION,
    EXAM_FORMAT,
    GENERATOR_VERSION,
    STATEMENTS,
    check_answer,
    generate,
    grade_band_tier,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def build_report(samples: int = 500, unique_target: int = 200) -> dict[str, object]:
    if samples < 1 or unique_target < 1:
        raise ValueError("samples and unique_target must be positive")
    masks: Counter[str] = Counter()
    positions: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    difficulty_bands: Counter[str] = Counter()
    fingerprints: set[tuple[str, ...]] = set()
    propositions: set[str] = set()
    proposition_pairs: set[tuple[str, str]] = set()
    statement_appearances: Counter[str] = Counter()
    length_spreads: list[int] = []
    failed_answers = 0
    for seed in range(samples):
        triple = generate(seed)
        snapshot = triple.snapshot()
        validate_snapshot(snapshot)
        masks[triple.answer_mask] += 1
        positions[triple.answer_mask] += 1
        topics.update(item.topic for item in triple.statements)
        difficulty_bands.update(
            {1: "introductory", 2: "core", 3: "extension"}[grade_band_tier(item.grade_band)]
            for item in triple.statements
        )
        fingerprints.add(tuple(sorted(item.proposition_id for item in triple.statements)))
        proposition_ids = [item.proposition_id for item in triple.statements]
        statement_appearances.update(item.id for item in triple.statements)
        propositions.update(proposition_ids)
        proposition_pairs.update(
            tuple(sorted(pair))
            for pair in (
                (proposition_ids[0], proposition_ids[1]),
                (proposition_ids[0], proposition_ids[2]),
                (proposition_ids[1], proposition_ids[2]),
            )
        )
        statement_lengths = [len(item.statement) for item in triple.statements]
        length_spreads.append(max(statement_lengths) - min(statement_lengths))
        if not check_answer(snapshot, triple.answer_mask):
            failed_answers += 1
    if failed_answers or len(fingerprints) < unique_target:
        raise RuntimeError(
            f"QA gate failed: {failed_answers} answer errors, "
            f"{len(fingerprints)} unique triples (<{unique_target})"
        )
    bank_ids = {item.id for item in STATEMENTS}
    unused_statement_ids = sorted(bank_ids - statement_appearances.keys())
    if unused_statement_ids:
        raise RuntimeError(
            f"QA sample left {len(unused_statement_ids)} statements unused: "
            f"{', '.join(unused_statement_ids)}"
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
        "bank_version": BANK_VERSION,
        "source_prototypes": matrix["source_count"],
        "statement_count": len(STATEMENTS),
        "true_statements": sum(item.is_true for item in STATEMENTS),
        "false_statements": sum(not item.is_true for item in STATEMENTS),
        "topic_count": len({item.topic for item in STATEMENTS}),
        "distinct_propositions_sampled": len(propositions),
        "distinct_proposition_pairs_sampled": len(proposition_pairs),
        "statements_sampled": len(statement_appearances),
        "unused_statement_ids": unused_statement_ids,
        "min_statement_appearances": min(statement_appearances.values()),
        "max_statement_appearances": max(statement_appearances.values()),
        "mean_statement_length_spread": round(sum(length_spreads) / samples, 2),
        "max_statement_length_spread": max(length_spreads),
        "samples": samples,
        "unique_triples": len(fingerprints),
        "unique_target": unique_target,
        "answer_mask_counts": dict(sorted(masks.items())),
        "correct_position_counts": dict(sorted(positions.items())),
        "topic_appearances": dict(sorted(topics.items())),
        "difficulty_band_appearances": dict(sorted(difficulty_bands.items())),
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
