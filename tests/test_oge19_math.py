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
    Statement,
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
    assert len(STATEMENTS) >= 6
    assert len({item.id for item in STATEMENTS}) == len(STATEMENTS)
    assert len({item.proposition_id for item in STATEMENTS}) == len(STATEMENTS)
    assert len({item.statement for item in STATEMENTS}) == len(STATEMENTS)
    assert len({item.source_task_id for item in STATEMENTS}) == 38
    assert sum(item.is_true for item in STATEMENTS) == 92
    assert sum(not item.is_true for item in STATEMENTS) == 80
    assert {f"OGE19-A{index:03d}" for index in range(1, 99)} <= {item.id for item in STATEMENTS}
    for item in STATEMENTS:
        assert item.source_task_id in source_ids
        assert item.source_url.endswith(f"id={item.source_task_id}")
        assert item.source_basis in {
            "source_statement",
            "source_solution_correction",
            "mathematical_derivation",
        }
        assert item.source_matrix_review_status in review_statuses
        assert item.is_true in {True, False}
        assert item.statement and item.explanation
        assert item.review_status == (
            "independently_proved" if item.is_true else "independently_counterexampled"
        )


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


def test_reviewed_claims_have_consistent_proofs_and_counterexamples() -> None:
    by_id = {item.id: item for item in STATEMENTS}
    median_area = by_id["OGE19-A110"]
    assert median_area.is_true
    assert "равные половины исходной стороны" in median_area.explanation
    assert "высота из противоположной вершины" in median_area.explanation

    tangent_chord = by_id["OGE19-A123"]
    assert tangent_chord.is_true
    assert "противоположном сегменте" in tangent_chord.statement
    assert "соответствующей дуги AB" in tangent_chord.explanation

    median_bisector = by_id["OGE19-A124"]
    assert not median_bisector.is_true
    assert median_bisector.statement == (
        "В любом треугольнике каждая медиана делит угол при своей вершине пополам."
    )
    assert all(part in median_bisector.explanation for part in ("5, 6 и 7", "3,5", "5:6"))

    equal_area = by_id["OGE19-A144"]
    assert not equal_area.is_true
    assert all(part in equal_area.explanation for part in ("2 и 6", "3 и 4", "равна 12"))


def test_previous_bank_version_four_remains_restorable() -> None:
    from app.math.oge19 import refresh_snapshot_digest

    snapshot = generate(912).snapshot()
    snapshot["bank_version"] = "oge19-claims-4"
    refresh_snapshot_digest(snapshot)
    assert restore(snapshot).statements == tuple(
        Statement.from_dict(item) for item in snapshot["statements"]
    )


def test_generation_is_deterministic_and_snapshots_restore() -> None:
    first = generate(20261117)
    second = generate(20261117)
    assert first.snapshot() == second.snapshot()
    restored = restore(first.snapshot())
    assert restored == first
    assert check_answer(first.snapshot(), first.answer_mask)
    assert not check_answer(first.snapshot(), "123")
    assert first.generator_version == GENERATOR_VERSION


def test_previous_snapshot_is_restored_without_rewriting_its_text() -> None:
    legacy = json.loads((ROOT / "tests/fixtures/oge19/snapshot_v1_seed_20261117.json").read_text())
    validate_snapshot(legacy)
    restored = restore(legacy)
    assert [item.statement for item in restored.statements] == [
        item["statement"] for item in legacy["statements"]
    ]
    assert restored.answer_mask == legacy["answer_mask"]


def test_schema_two_snapshot_keeps_its_pinned_bank_text() -> None:
    snapshot = generate(912).snapshot()
    snapshot["bank_version"] = "oge19-claims-2"
    from hashlib import sha256

    body = {key: value for key, value in snapshot.items() if key != "content_hash"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot["content_hash"] = sha256(canonical.encode()).hexdigest()
    assert restore(snapshot).statements == tuple(
        Statement.from_dict(item) for item in snapshot["statements"]
    )


@pytest.mark.mass
def test_500_seed_sample_covers_the_bank_with_diverse_one_true_triples() -> None:
    fingerprints: set[tuple[str, ...]] = set()
    used_ids: set[str] = set()
    for seed in range(500):
        triple = generate(seed)
        assert len(triple.statements) == 3
        assert len({item.topic for item in triple.statements}) == 3
        assert len({item.proposition_id for item in triple.statements}) == 3
        assert answer_mask(triple.statements) == triple.answer_mask
        assert len(triple.answer_mask) == 1
        assert validate_snapshot(triple.snapshot()) is None
        used_ids.update(item.id for item in triple.statements)
        fingerprints.add(tuple(sorted(item.proposition_id for item in triple.statements)))
    assert len(fingerprints) >= 200
    assert used_ids == {item.id for item in STATEMENTS}


def test_theme_filter_and_position_balancing() -> None:
    from app.math.oge19 import THEME_TOPICS

    counts = [0, 0, 0]
    for seed in range(90):
        triple = generate(seed, correct_position_counts=tuple(counts))
        counts[int(triple.answer_mask) - 1] += 1
    assert max(counts) - min(counts) <= 1
    for theme, topics in THEME_TOPICS.items():
        sample = generate(811, theme=theme)
        assert len(sample.statements) == 3
        assert all(item.topic in topics for item in sample.statements)
        assert len(sample.answer_mask) == 1


@pytest.mark.mass
def test_each_thematic_pool_is_covered_without_leaking_other_topics() -> None:
    from app.math.oge19 import THEME_TOPICS

    for theme, topics in THEME_TOPICS.items():
        allowed = {item.id for item in STATEMENTS if item.topic in topics}
        sampled: set[str] = set()
        for seed in range(500):
            triple = generate(seed, theme=theme)
            assert all(item.topic in topics for item in triple.statements)
            sampled.update(item.id for item in triple.statements)
        assert sampled == allowed


@pytest.mark.mass
def test_generated_statements_have_similar_visible_lengths() -> None:
    spreads = []
    for seed in range(500):
        triple = generate(seed)
        lengths = [len(item.statement) for item in triple.statements]
        spreads.append(max(lengths) - min(lengths))
    assert max(spreads) <= 25


def test_previous_schema_two_generator_snapshot_remains_restorable() -> None:
    snapshot = json.loads(
        (ROOT / "tests/fixtures/oge19/snapshot_v2_seed_912.json").read_text(encoding="utf-8")
    )
    validate_snapshot(snapshot)
    restored = restore(snapshot)
    assert restored.generator_version == "oge19-triples-2"
    assert [item.statement for item in restored.statements] == [
        item["statement"] for item in snapshot["statements"]
    ]


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
