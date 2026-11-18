"""Verified OGE #19 statement bank and deterministic, snapshot-safe triple builder."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, cast

LEGACY_GENERATOR_VERSION = "oge19-triples-1"
GENERATOR_VERSION = "oge19-triples-3"
SUPPORTED_GENERATOR_VERSIONS = frozenset({"oge19-triples-2", GENERATOR_VERSION})
ANSWER_POLICY_ID = "oge19.answer-single-true"
ANSWER_POLICY_VERSION = "1"
SNAPSHOT_SCHEMA_VERSION = 2
EXAM_FORMAT = "single_true_statement"


@dataclass(frozen=True, slots=True)
class Statement:
    id: str
    proposition_id: str
    topic: str
    grade_band: str
    statement: str
    is_true: bool
    explanation: str
    source_task_id: str
    source_url: str
    source_basis: str
    source_matrix_review_status: str
    review_status: str = "independently_proved"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "proposition_id": self.proposition_id,
            "topic": self.topic,
            "grade_band": self.grade_band,
            "statement": self.statement,
            "is_true": self.is_true,
            "explanation": self.explanation,
            "source": {
                "task_id": self.source_task_id,
                "url": self.source_url,
                "basis": self.source_basis,
                "matrix_review_status": self.source_matrix_review_status,
            },
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> Statement:
        source = item["source"]
        return cls(
            id=str(item["id"]),
            proposition_id=str(item["proposition_id"]),
            topic=str(item["topic"]),
            grade_band=str(item["grade_band"]),
            statement=str(item["statement"]),
            is_true=item["is_true"],
            explanation=str(item["explanation"]),
            source_task_id=str(source["task_id"]),
            source_url=str(source["url"]),
            source_basis=str(source["basis"]),
            source_matrix_review_status=str(source["matrix_review_status"]),
            review_status=str(item.get("review_status", "independently_proved")),
        )


def _load_bank() -> tuple[Statement, ...]:
    path = Path(__file__).with_name("oge19_bank.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    statements = tuple(Statement.from_dict(item) for item in raw["items"])
    if len(statements) < 6:
        raise ValueError("OGE19 bank cannot construct any three-item task")
    if len({item.id for item in statements}) != len(statements):
        raise ValueError("OGE19 statement IDs must be unique")
    if len({item.proposition_id for item in statements}) != len(statements):
        raise ValueError("OGE19 propositions must be unique")
    if any(not item.statement.strip() or not item.explanation.strip() for item in statements):
        raise ValueError("Each OGE19 statement needs text and a proof or counterexample")
    if any(
        item.review_status
        != ("independently_proved" if item.is_true else "independently_counterexampled")
        for item in statements
    ):
        raise ValueError("Every OGE19 statement needs an independent mathematical review")
    if any(
        item.source_matrix_review_status not in {"verified_answer", "catalog_analyzed"}
        for item in statements
    ):
        raise ValueError("Each OGE19 source must have an accepted review status")
    if any(item.source_task_id == "461001" for item in statements):
        raise ValueError("Conflicted source 461001 is excluded")
    if not any(item.is_true for item in statements) or not any(
        not item.is_true for item in statements
    ):
        raise ValueError("The OGE19 bank needs both true and false statements")
    return statements


STATEMENTS = _load_bank()
STATEMENTS_BY_ID = {item.id: item for item in STATEMENTS}
BANK_VERSION = str(
    json.loads(Path(__file__).with_name("oge19_bank.json").read_text(encoding="utf-8"))[
        "bank_version"
    ]
)
SUPPORTED_BANK_VERSIONS = frozenset(
    {"oge19-claims-1", "oge19-claims-2", "oge19-claims-3", "oge19-claims-4", BANK_VERSION}
)


class ChoiceNumberPolicy:
    policy_id = ANSWER_POLICY_ID
    version = ANSWER_POLICY_VERSION

    @staticmethod
    def parse(raw: str) -> str | None:
        value = raw.strip()
        return value if re.fullmatch(r"[123]", value) else None

    def accepts(self, raw: str, expected: str) -> bool:
        parsed = self.parse(raw)
        return parsed is not None and parsed == expected


POLICY = ChoiceNumberPolicy()


@dataclass(frozen=True, slots=True)
class Triple:
    statements: tuple[Statement, Statement, Statement]
    answer_mask: str
    seed: int
    generator_version: str = GENERATOR_VERSION

    def snapshot(self) -> dict[str, object]:
        body: dict[str, object] = {
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "bank_version": BANK_VERSION,
            "generator_version": self.generator_version,
            "answer_policy_id": ANSWER_POLICY_ID,
            "answer_policy_version": ANSWER_POLICY_VERSION,
            "seed": self.seed,
            "answer_mask": self.answer_mask,
            "statements": [statement.to_dict() for statement in self.statements],
        }
        body["content_hash"] = _digest(body)
        return body


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def refresh_snapshot_digest(snapshot: dict[str, object]) -> None:
    """Seal stable snapshot fields while excluding scheduler-only underscore metadata."""
    body = {
        key: value
        for key, value in snapshot.items()
        if key != "content_hash" and not key.startswith("_")
    }
    snapshot["content_hash"] = _digest(body)


def answer_mask(statements: tuple[Statement, ...] | list[Statement]) -> str:
    return "".join(str(index) for index, statement in enumerate(statements, 1) if statement.is_true)


THEME_TOPICS = {
    "triangles": {
        "triangle_angles",
        "triangle_inequality",
        "triangle_congruence",
        "isosceles_triangle",
        "triangle_similarity",
        "triangle_centers",
        "right_triangle",
    },
    "quadrilaterals": {"quadrilaterals", "trapezoids"},
    "circles": {"circles", "tangency"},
    "lines_angles": {"angles_lines"},
    "areas_metrics": {"areas", "right_triangle", "triangle_inequality"},
}


def grade_band_tier(grade_band: str) -> int:
    """Use the upper school grade in the reviewed band as a rough difficulty proxy."""
    try:
        upper_grade = int(grade_band.split("-")[-1])
    except ValueError:
        return 2
    return 1 if upper_grade <= 7 else 2 if upper_grade == 8 else 3


def generate(
    seed: int,
    *,
    generator_version: str = GENERATOR_VERSION,
    theme: str | None = None,
    recent_proposition_ids: tuple[str, ...] = (),
    correct_position_counts: tuple[int, int, int] = (0, 0, 0),
) -> Triple:
    """Build a deterministic exam-format triple with bounded learner history."""
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported generator version: {generator_version}")
    rng = random.Random(seed)
    pool = [
        item
        for item in STATEMENTS
        if theme is None or theme == "mixed" or item.topic in THEME_TOPICS.get(theme, set())
    ]
    if theme not in {None, "mixed", *THEME_TOPICS}:
        raise ValueError(f"Unknown OGE19 theme: {theme}")
    # Prefer unseen atomic ideas; if history exhausts a small theme pool, relax it
    # deterministically and keep generation total rather than spinning.
    fresh = [item for item in pool if item.proposition_id not in set(recent_proposition_ids[-30:])]
    if sum(item.is_true for item in fresh) >= 1 and sum(not item.is_true for item in fresh) >= 2:
        pool = fresh
    true_items = [x for x in pool if x.is_true]
    false_items = [x for x in pool if not x.is_true]
    if not true_items or len(false_items) < 2:
        raise ValueError("Selected OGE19 theme needs at least one true and two false statements")
    # Anchor one available proposition by seed. This prevents the length/topic
    # ranking from permanently excluding unusual but valid claims. Complementary
    # claims are still chosen by the same topic, grade-band and length priorities.
    anchor = pool[seed % len(pool)]
    candidate_sets: list[tuple[tuple[int, int, int], Statement, list[Statement]]] = []
    if anchor.is_true:
        combinations_for_anchor = (
            (anchor, first_false, second_false)
            for first_false, second_false in combinations(false_items, 2)
        )
    else:
        combinations_for_anchor = (
            (true_candidate, anchor, other_false)
            for true_candidate in true_items
            for other_false in false_items
            if other_false.id != anchor.id
        )
    for true_candidate, first_false, second_false in combinations_for_anchor:
        false_pair = [first_false, second_false]
        distinct_topics = len({true_candidate.topic, *(item.topic for item in false_pair)}) == 3
        lengths = [len(true_candidate.statement), *(len(item.statement) for item in false_pair)]
        spread = max(lengths) - min(lengths)
        tiers = {grade_band_tier(item.grade_band) for item in [true_candidate, *false_pair]}
        # Mixed practice prefers topic variety, then similar statement lengths.
        topic_penalty = int(theme in {None, "mixed"} and not distinct_topics)
        grade_penalty = int(len(tiers) == 1)
        score = (topic_penalty, grade_penalty, spread)
        if not candidate_sets or score < candidate_sets[0][0]:
            candidate_sets = [(score, true_candidate, false_pair)]
        elif score == candidate_sets[0][0]:
            candidate_sets.append((score, true_candidate, false_pair))
    _, true_item, false_items_chosen = rng.choice(candidate_sets)
    least_used = min(correct_position_counts)
    positions = [i for i, count in enumerate(correct_position_counts) if count == least_used]
    correct_pos = positions[seed % len(positions)]
    rng.shuffle(false_items_chosen)
    result: list[Statement | None] = [None, None, None]
    result[correct_pos] = true_item
    remaining = iter(false_items_chosen)
    for index in range(3):
        if result[index] is None:
            result[index] = next(remaining)
    chosen = cast(tuple[Statement, Statement, Statement], tuple(result))
    triple = Triple(chosen, answer_mask(chosen), seed, generator_version)
    validate_snapshot(triple.snapshot())
    return triple


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Fail closed on unknown versions, modified content, or a wrong answer mask."""
    schema = snapshot.get("snapshot_schema_version")
    version = snapshot.get("generator_version")
    if schema == 1 and version == LEGACY_GENERATOR_VERSION:
        _validate_legacy_snapshot(snapshot)
        return
    if schema != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Unsupported OGE19 snapshot schema version")
    if version not in SUPPORTED_GENERATOR_VERSIONS:
        raise ValueError("Unsupported OGE19 generator version")
    if snapshot.get("answer_policy_id") != ANSWER_POLICY_ID:
        raise ValueError("Unsupported OGE19 answer policy")
    if snapshot.get("answer_policy_version") != ANSWER_POLICY_VERSION:
        raise ValueError("Unsupported OGE19 answer policy version")
    supplied_hash = snapshot.get("content_hash")
    body = {
        key: value
        for key, value in snapshot.items()
        if key != "content_hash" and not key.startswith("_")
    }
    if supplied_hash != _digest(body):
        raise ValueError("OGE19 snapshot content hash mismatch")
    raw = snapshot.get("statements")
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError("An OGE19 snapshot must contain exactly three statements")
    statements = tuple(Statement.from_dict(item) for item in raw)
    if len({item.id for item in statements}) != 3:
        raise ValueError("An OGE19 triple must contain three distinct statements")
    if len({item.proposition_id for item in statements}) != 3:
        raise ValueError("An OGE19 triple must contain three distinct propositions")
    if schema == 1 and len({item.topic for item in statements}) != 3:
        raise ValueError("An OGE19 legacy triple must mix three topics")
    actual_mask = answer_mask(statements)
    if len(actual_mask) != 1 or snapshot.get("answer_mask") != actual_mask:
        raise ValueError("OGE19 answer mask does not match the true statements")
    if snapshot.get("bank_version") not in SUPPORTED_BANK_VERSIONS:
        raise ValueError("Unsupported OGE19 bank version")
    for statement in statements:
        if (
            not statement.statement.strip()
            or not statement.explanation.strip()
            or statement.review_status
            != ("independently_proved" if statement.is_true else "independently_counterexampled")
        ):
            raise ValueError("OGE19 snapshot contains an unreviewed statement")


def _validate_legacy_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Read-only v1 compatibility; issued text remains authoritative in its signed snapshot."""
    if (
        snapshot.get("answer_policy_id") != ANSWER_POLICY_ID
        or snapshot.get("answer_policy_version") != "1"
    ):
        raise ValueError("Unsupported legacy OGE19 answer policy")
    body = {key: value for key, value in snapshot.items() if key != "content_hash"}
    if snapshot.get("content_hash") != _digest(body):
        raise ValueError("OGE19 snapshot content hash mismatch")
    raw = snapshot.get("statements")
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError("An OGE19 snapshot must contain exactly three statements")
    statements = tuple(Statement.from_dict(item) for item in raw)
    if (
        len({x.id for x in statements}) != 3
        or answer_mask(statements) != snapshot.get("answer_mask")
        or len(answer_mask(statements)) != 1
    ):
        raise ValueError("OGE19 answer mask does not match the true statements")
    if len({x.topic for x in statements}) != 3:
        raise ValueError("An OGE19 legacy triple must mix three topics")
    for item in statements:
        if not item.statement.strip() or not item.explanation.strip():
            raise ValueError("Legacy OGE19 statement lacks pinned text or explanation")


def restore(snapshot: Mapping[str, Any]) -> Triple:
    validate_snapshot(snapshot)
    raw = snapshot["statements"]
    restored = [Statement.from_dict(item) for item in raw]
    statements = (restored[0], restored[1], restored[2])
    version = snapshot.get("generator_version")
    restored_version = version if version in SUPPORTED_GENERATOR_VERSIONS else GENERATOR_VERSION
    return Triple(statements, str(snapshot["answer_mask"]), int(snapshot["seed"]), restored_version)


def check_answer(snapshot: Mapping[str, Any], submitted: str) -> bool:
    validate_snapshot(snapshot)
    return submitted.strip() == str(snapshot["answer_mask"])
