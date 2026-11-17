from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from app.math.oge19 import (
    ANSWER_POLICY_ID,
    ANSWER_POLICY_VERSION,
    EXAM_FORMAT,
    GENERATOR_VERSION,
    STATEMENTS,
    Triple,
    answer_mask,
    check_answer,
    generate,
    restore,
    validate_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bank_has_unique_reviewed_claims_and_known_sources() -> None:
    matrix = json.loads((ROOT / "specs/research/oge19/SOURCE_MATRIX.json").read_text())
    source_ids = {str(item["source_id"]) for item in matrix["sources"]}
    review_statuses = {item["review_status"] for item in matrix["sources"]}
    assert 80 <= len(STATEMENTS) <= 120
    assert len({item.id for item in STATEMENTS}) == len(STATEMENTS)
    assert len({item.proposition_id for item in STATEMENTS}) == len(STATEMENTS)
    assert len({item.statement for item in STATEMENTS}) == len(STATEMENTS)
    for item in STATEMENTS:
        assert item.source_task_id in source_ids
        assert item.source_url.endswith(f"id={item.source_task_id}")
        assert item.source_basis in {"source_statement", "source_solution_correction"}
        assert item.source_matrix_review_status in review_statuses
        assert item.is_true in {True, False}
        assert item.statement and item.explanation


def test_fipi_exam_contract_uses_exactly_one_true_statement() -> None:
    assert EXAM_FORMAT == "single_true_statement"
    assert ANSWER_POLICY_ID == "oge19.answer-single-true"
    assert ANSWER_POLICY_VERSION == "1"


def test_high_risk_facts_are_pinned() -> None:
    by_key = {item.proposition_id: item for item in STATEMENTS}
    assert by_key["obtuse_triangle.all_angles_obtuse"].is_true is False
    assert by_key["rectangle.diagonals_four_congruent"].is_true is False
    assert by_key["rhombus.incircle"].is_true is True
    assert by_key["trapezoid.midline_half_sum"].is_true is True
    assert by_key["trapezoid.midline_sum"].is_true is False
    assert by_key["circle.inscribed_half_central"].is_true is True
    assert by_key["circle.inscribed_equals_central"].is_true is False
    assert all(item.source_task_id != "461001" for item in STATEMENTS)


def test_generation_is_deterministic_and_snapshots_restore() -> None:
    first = generate(20261117)
    second = generate(20261117)
    assert first.snapshot() == second.snapshot()
    restored = restore(first.snapshot())
    assert restored == first
    assert check_answer(first.snapshot(), first.answer_mask)
    assert not check_answer(first.snapshot(), "123")
    assert first.generator_version == GENERATOR_VERSION


def test_many_seeds_have_three_distinct_topics_and_one_true_answer() -> None:
    fingerprints: set[tuple[str, ...]] = set()
    for seed in range(300):
        triple = generate(seed)
        assert len(triple.statements) == 3
        assert len({item.topic for item in triple.statements}) == 3
        assert len({item.proposition_id for item in triple.statements}) == 3
        assert answer_mask(triple.statements) == triple.answer_mask
        assert len(triple.answer_mask) == 1
        assert validate_snapshot(triple.snapshot()) is None
        fingerprints.add(tuple(sorted(item.proposition_id for item in triple.statements)))
    assert len(fingerprints) >= 200


def test_answer_mask_tracks_each_possible_position() -> None:
    true_statement = next(item for item in STATEMENTS if item.is_true)
    false_statements = [item for item in STATEMENTS if not item.is_true]
    for false_one, false_two in itertools.combinations(false_statements, 2):
        if len({true_statement.topic, false_one.topic, false_two.topic}) == 3:
            base = (true_statement, false_one, false_two)
            break
    else:
        pytest.fail("Bank has no three-topic one-true combination")
    masks = set()
    for ordered in itertools.permutations(base):
        mask = answer_mask(ordered)
        assert len(mask) == 1
        snapshot = Triple(ordered, mask, 1).snapshot()
        assert restore(snapshot).answer_mask == mask
        masks.add(mask)
    assert masks == {"1", "2", "3"}


def test_snapshot_rejects_changed_content_wrong_mask_and_unknown_versions() -> None:
    snapshot = generate(7).snapshot()
    tampered = dict(snapshot)
    tampered["answer_mask"] = "123"
    with pytest.raises(ValueError, match="content hash"):
        validate_snapshot(tampered)

    wrong_version = dict(snapshot)
    wrong_version["answer_policy_version"] = "999"
    with pytest.raises(ValueError, match="policy version"):
        validate_snapshot(wrong_version)

    unknown_generator = dict(snapshot)
    unknown_generator["generator_version"] = "future"
    with pytest.raises(ValueError, match="generator version"):
        validate_snapshot(unknown_generator)


def test_snapshot_does_not_accept_mask_that_disagrees_with_truth_values() -> None:
    snapshot = generate(9).snapshot()
    snapshot["answer_mask"] = "1" if snapshot["answer_mask"] != "1" else "2"
    # Recompute the checksum so this exercises the independent mask check.
    from hashlib import sha256

    body = {key: value for key, value in snapshot.items() if key != "content_hash"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot["content_hash"] = sha256(canonical.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="answer mask"):
        validate_snapshot(snapshot)
