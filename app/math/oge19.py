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
GENERATOR_VERSION = "oge19-triples-5"
SUPPORTED_GENERATOR_VERSIONS = frozenset(
    {"oge19-triples-2", "oge19-triples-3", "oge19-triples-4", GENERATOR_VERSION}
)
LEGACY_ANSWER_POLICY_ID = "oge19.answer-single-true"
LEGACY_ANSWER_POLICY_VERSION = "1"
ANSWER_POLICY_ID = "oge19.answer-statement-set"
ANSWER_POLICY_VERSION = "2"
SNAPSHOT_SCHEMA_VERSION = 2
EXAM_FORMAT = "one_or_multiple_true_statements"


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
    {
        "oge19-claims-1",
        "oge19-claims-2",
        "oge19-claims-3",
        "oge19-claims-4",
        "oge19-claims-5",
        BANK_VERSION,
    }
)


class SingleChoiceNumberPolicy:
    """Read-only answer behavior for already issued one-true snapshots."""

    policy_id = LEGACY_ANSWER_POLICY_ID
    version = LEGACY_ANSWER_POLICY_VERSION

    @staticmethod
    def parse(raw: str) -> str | None:
        value = raw.strip()
        return value if re.fullmatch(r"[123]", value) else None

    def accepts(self, raw: str, expected: str) -> bool:
        parsed = self.parse(raw)
        return parsed is not None and parsed == expected


class StatementSetPolicy:
    policy_id = ANSWER_POLICY_ID
    version = ANSWER_POLICY_VERSION

    @staticmethod
    def parse(raw: str) -> str | None:
        value = raw.strip()
        if not re.fullmatch(r"[123]{1,3}", value) or len(set(value)) != len(value):
            return None
        return "".join(sorted(value))

    def accepts(self, raw: str, expected: str) -> bool:
        parsed = self.parse(raw)
        return parsed is not None and parsed == "".join(sorted(expected))


LEGACY_POLICY = SingleChoiceNumberPolicy()
POLICY = StatementSetPolicy()
ANSWER_POLICIES: dict[
    tuple[str, str], SingleChoiceNumberPolicy | StatementSetPolicy
] = {
    (LEGACY_ANSWER_POLICY_ID, LEGACY_ANSWER_POLICY_VERSION): LEGACY_POLICY,
    (ANSWER_POLICY_ID, ANSWER_POLICY_VERSION): POLICY,
}


def policy_for_snapshot(
    snapshot: Mapping[str, Any],
) -> SingleChoiceNumberPolicy | StatementSetPolicy | None:
    return ANSWER_POLICIES.get(
        (
            str(snapshot.get("answer_policy_id", "")),
            str(snapshot.get("answer_policy_version", "")),
        )
    )


@dataclass(frozen=True, slots=True)
class Triple:
    statements: tuple[Statement, Statement, Statement]
    answer_mask: str
    seed: int
    generator_version: str = GENERATOR_VERSION
    answer_policy_id: str = ANSWER_POLICY_ID
    answer_policy_version: str = ANSWER_POLICY_VERSION

    find_false: bool = False

    def snapshot(self) -> dict[str, object]:
        body: dict[str, object] = {
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "bank_version": BANK_VERSION,
            "generator_version": self.generator_version,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "seed": self.seed,
            "answer_mask": self.answer_mask,
            "statements": [statement.to_dict() for statement in self.statements],
        }
        if self.generator_version == GENERATOR_VERSION:
            body["question_kind"] = "find_false" if self.find_false else "find_true"
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


def question_heading(find_false: bool) -> str:
    if find_false:
        return (
            "Тренировочный вариант. Какие из следующих утверждений неверны? "
            "В ответ запишите их номера."
        )
    return "Какие из следующих утверждений верны? В ответ запишите их номера."


def answer_mask(
    statements: tuple[Statement, ...] | list[Statement], *, find_false: bool = False
) -> str:
    return "".join(
        str(index) for index, statement in enumerate(statements, 1)
        if statement.is_true != find_false
    )


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

# The bank contains some near-opposite formulations from different cards. Keep
# those out of the same generated task even though each item is reviewed alone.
INCOMPATIBLE_PROPOSITION_PAIRS = frozenset(
    {
        frozenset({"circle.inscribed_half_central", "circle.inscribed_equals_central"}),
        frozenset({"trapezoid.midline_half_sum", "trapezoid.midline_sum"}),
        frozenset({"square.is_rhombus", "square_not_rhombus_exists"}),
        frozenset({"triangle.circumcenter_inside", "triangle.circumcenter_always_inside"}),
        frozenset({"triangle.two_obtuse_possible", "triangle.two_angles_obtuse"}),
    }
)


def grade_band_tier(grade_band: str) -> int:
    """Use the upper school grade in the reviewed band as a rough difficulty proxy."""
    try:
        upper_grade = int(grade_band.split("-")[-1])
    except ValueError:
        return 2
    return 1 if upper_grade <= 7 else 2 if upper_grade == 8 else 3


class NoCompatibleTriple(ValueError):
    """The current history and anchor leave no eligible three claims."""


def generate(
    seed: int,
    *,
    generator_version: str = GENERATOR_VERSION,
    theme: str | None = None,
    find_false: bool = False,
    target_count: int | None = None,
    recent_proposition_ids: tuple[str, ...] = (),
    excluded_fingerprints: frozenset[str] = frozenset(),
    correct_position_counts: tuple[int, int, int] = (0, 0, 0),
) -> Triple:
    """Build a deterministic exam-format triple with bounded learner history."""
    if generator_version not in {GENERATOR_VERSION, "oge19-triples-4"} or (
        generator_version != GENERATOR_VERSION and (find_false or target_count is not None)
    ):
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
    count = 1 + seed % 2 if target_count is None else target_count
    if count not in (1, 2):
        raise ValueError("Expected one or two requested statements")
    true_count = 3 - count if find_false else count
    if find_false:
        a, b, c = correct_position_counts
        correct_position_counts = (-a, -b, -c)
    if sum(item.is_true for item in fresh) >= true_count and sum(
        not item.is_true for item in fresh
    ) >= 3 - true_count:
        pool = fresh
    true_items = [x for x in pool if x.is_true]
    false_items = [x for x in pool if not x.is_true]
    if len(true_items) < true_count or len(false_items) < 3 - true_count:
        raise ValueError("Selected OGE19 theme has too few reviewed statements")
    # Anchor one available proposition by seed. This prevents the length/topic
    # ranking from permanently excluding unusual but valid claims. Complementary
    # claims are still chosen by the same topic, grade-band and length priorities.
    anchor = pool[seed % len(pool)]
    candidate_sets: list[tuple[tuple[int, int, int], tuple[Statement, ...]]] = []
    true_groups: list[tuple[Statement, ...]]
    false_groups: list[tuple[Statement, ...]]
    if anchor.is_true:
        true_groups = (
            [(anchor,)]
            if true_count == 1
            else [(anchor, other) for other in true_items if other.id != anchor.id]
        )
        false_groups = list(
            combinations(false_items, 3 - true_count)
        )
    else:
        true_groups = list(combinations(true_items, true_count))
        false_groups = (
            [(anchor,)]
            if 3 - true_count == 1
            else [(anchor, other) for other in false_items if other.id != anchor.id]
        )
    combinations_for_task = (
        (*true_group, *false_group) for true_group in true_groups for false_group in false_groups
    )
    for selected in combinations_for_task:
        if anchor not in selected:
            continue
        proposition_pair_keys = (
            frozenset((first.proposition_id, second.proposition_id))
            for first, second in combinations(selected, 2)
        )
        if any(pair in INCOMPATIBLE_PROPOSITION_PAIRS for pair in proposition_pair_keys):
            continue
        # Avoid presenting two claims taken from the same source question as if
        # they were independently sampled assertions.
        if len({item.source_task_id for item in selected}) != 3:
            continue
        if (
            excluded_fingerprints
            and ":".join(sorted(item.proposition_id for item in selected)) in excluded_fingerprints
        ):
            continue
        distinct_topics = len({item.topic for item in selected}) == 3
        lengths = [len(item.statement) for item in selected]
        spread = max(lengths) - min(lengths)
        tiers = {grade_band_tier(item.grade_band) for item in selected}
        # Mixed practice prefers topic variety, then similar statement lengths.
        topic_penalty = int(theme in {None, "mixed"} and not distinct_topics)
        grade_penalty = int(len(tiers) == 1)
        score = (topic_penalty, grade_penalty, spread)
        if not candidate_sets or score < candidate_sets[0][0]:
            candidate_sets = [(score, selected)]
        elif score == candidate_sets[0][0]:
            candidate_sets.append((score, selected))
    if not candidate_sets:
        raise NoCompatibleTriple("Selected OGE19 theme has no compatible statement triple")
    _, selected = rng.choice(candidate_sets)
    true_statements = [item for item in selected if item.is_true]
    false_statements = [item for item in selected if not item.is_true]
    rng.shuffle(true_statements)
    if true_count == 1:
        least_used = min(correct_position_counts)
        positions = [i for i, count in enumerate(correct_position_counts) if count == least_used]
        true_position = positions[seed % len(positions)]
        chosen_list: list[Statement] = []
        for index in range(3):
            chosen_list.append(
                true_statements[0] if index == true_position else false_statements.pop()
            )
    else:
        most_used = max(correct_position_counts)
        false_positions = [
            i for i, count in enumerate(correct_position_counts) if count == most_used
        ]
        false_position = false_positions[seed % len(false_positions)]
        chosen_list = []
        for index in range(3):
            chosen_list.append(
                false_statements[0] if index == false_position else true_statements.pop()
            )
    chosen = cast(tuple[Statement, Statement, Statement], tuple(chosen_list))
    triple = Triple(
        chosen,
        answer_mask(chosen, find_false=find_false),
        seed,
        generator_version,
        find_false=find_false,
    )
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
    policy_id = str(snapshot.get("answer_policy_id", ""))
    policy = policy_for_snapshot(snapshot)
    if policy is None:
        if any(policy_id == key[0] for key in ANSWER_POLICIES):
            raise ValueError("Unsupported OGE19 answer policy version")
        raise ValueError("Unsupported OGE19 answer policy")
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
    kind = snapshot.get("question_kind", "find_true")
    if kind not in {"find_true", "find_false"} or (
        version != GENERATOR_VERSION and kind != "find_true"
    ):
        raise ValueError("Incompatible question kind")
    find_false = kind == "find_false"
    actual_mask = answer_mask(statements, find_false=find_false)
    if version == GENERATOR_VERSION and "condition" in snapshot:
        expected = (
            question_heading(find_false)
            + "\n\n"
            + "\n".join(f"{i}. {item.statement}" for i, item in enumerate(statements, 1))
        )
        if snapshot["condition"] != expected or snapshot.get("correct_answer") != actual_mask:
            raise ValueError("Question disagrees with statement selection")
    valid_count = (
        len(actual_mask) == 1
        if policy is LEGACY_POLICY
        else len(actual_mask) in {1, 2}
    )
    if not valid_count or snapshot.get("answer_mask") != actual_mask:
        raise ValueError("OGE19 answer mask does not match the true statements")
    if snapshot.get("bank_version") not in SUPPORTED_BANK_VERSIONS:
        raise ValueError("Unsupported OGE19 bank version")
    if snapshot.get("bank_version") == BANK_VERSION and any(
        STATEMENTS_BY_ID.get(statement.id) != statement for statement in statements
    ):
        raise ValueError("OGE19 snapshot claim differs from the reviewed bank")
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
        snapshot.get("answer_policy_id") != LEGACY_ANSWER_POLICY_ID
        or snapshot.get("answer_policy_version") != LEGACY_ANSWER_POLICY_VERSION
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
    return Triple(
        statements,
        str(snapshot["answer_mask"]),
        int(snapshot["seed"]),
        restored_version,
        str(snapshot.get("answer_policy_id", LEGACY_ANSWER_POLICY_ID)),
        str(snapshot.get("answer_policy_version", LEGACY_ANSWER_POLICY_VERSION)),
        snapshot.get("question_kind") == "find_false",
    )


def check_answer(snapshot: Mapping[str, Any], submitted: str) -> bool:
    validate_snapshot(snapshot)
    policy = policy_for_snapshot(snapshot)
    return policy is not None and policy.accepts(submitted, str(snapshot["answer_mask"]))
