"""Verified OGE #19 statement bank and deterministic, snapshot-safe triple builder."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "oge19-triples-1"
ANSWER_POLICY_ID = "oge19.answer-single-true"
ANSWER_POLICY_VERSION = "1"
SNAPSHOT_SCHEMA_VERSION = 1
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
        )


def _load_bank() -> tuple[Statement, ...]:
    path = Path(__file__).with_name("oge19_bank.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw["bank_version"] != "oge19-claims-1":
        raise ValueError("Unsupported OGE19 bank version")
    statements = tuple(Statement.from_dict(item) for item in raw["items"])
    if not 80 <= len(statements) <= 120:
        raise ValueError("OGE19 bank must contain between 80 and 120 claims")
    if len({item.id for item in statements}) != len(statements):
        raise ValueError("OGE19 statement IDs must be unique")
    if len({item.proposition_id for item in statements}) != len(statements):
        raise ValueError("OGE19 propositions must be unique")
    if any(not item.statement.strip() or not item.explanation.strip() for item in statements):
        raise ValueError("Each OGE19 statement needs text and a proof or counterexample")
    if any(item.source_task_id == "461001" for item in statements):
        raise ValueError("Conflicted source 461001 is excluded")
    if not any(item.is_true for item in statements) or not any(
        not item.is_true for item in statements
    ):
        raise ValueError("The OGE19 bank needs both true and false statements")
    return statements


STATEMENTS = _load_bank()
STATEMENTS_BY_ID = {item.id: item for item in STATEMENTS}


@dataclass(frozen=True, slots=True)
class Triple:
    statements: tuple[Statement, Statement, Statement]
    answer_mask: str
    seed: int
    generator_version: str = GENERATOR_VERSION

    def snapshot(self) -> dict[str, object]:
        body: dict[str, object] = {
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
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


def answer_mask(statements: tuple[Statement, ...] | list[Statement]) -> str:
    return "".join(str(index) for index, statement in enumerate(statements, 1) if statement.is_true)


def generate(seed: int, *, generator_version: str = GENERATOR_VERSION) -> Triple:
    """Build one exam-format triple with exactly one true statement."""
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported generator version: {generator_version}")
    rng = random.Random(seed)
    for _ in range(256):
        sample = rng.sample(STATEMENTS, 3)
        chosen = (sample[0], sample[1], sample[2])
        if len({item.proposition_id for item in chosen}) != 3:
            continue
        if len({item.topic for item in chosen}) != 3:
            continue
        mask = answer_mask(chosen)
        if len(mask) == 1:
            triple = Triple(chosen, mask, seed)
            validate_snapshot(triple.snapshot())
            return triple
    raise RuntimeError("Could not construct a valid OGE19 triple within the attempt limit")


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Fail closed on unknown versions, modified content, or a wrong answer mask."""
    if snapshot.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Unsupported OGE19 snapshot schema version")
    if snapshot.get("generator_version") != GENERATOR_VERSION:
        raise ValueError("Unsupported OGE19 generator version")
    if snapshot.get("answer_policy_id") != ANSWER_POLICY_ID:
        raise ValueError("Unsupported OGE19 answer policy")
    if snapshot.get("answer_policy_version") != ANSWER_POLICY_VERSION:
        raise ValueError("Unsupported OGE19 answer policy version")
    supplied_hash = snapshot.get("content_hash")
    body = {key: value for key, value in snapshot.items() if key != "content_hash"}
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
    if len({item.topic for item in statements}) != 3:
        raise ValueError("An OGE19 triple must mix three topics")
    actual_mask = answer_mask(statements)
    if len(actual_mask) != 1 or snapshot.get("answer_mask") != actual_mask:
        raise ValueError("OGE19 answer mask does not match the true statements")
    for statement in statements:
        if statement.id not in STATEMENTS_BY_ID:
            raise ValueError("Unknown OGE19 statement ID")
        if STATEMENTS_BY_ID[statement.id] != statement:
            raise ValueError("OGE19 statement differs from the pinned bank version")


def restore(snapshot: Mapping[str, Any]) -> Triple:
    validate_snapshot(snapshot)
    raw = snapshot["statements"]
    restored = [Statement.from_dict(item) for item in raw]
    statements = (restored[0], restored[1], restored[2])
    return Triple(statements, str(snapshot["answer_mask"]), int(snapshot["seed"]))


def check_answer(snapshot: Mapping[str, Any], submitted: str) -> bool:
    validate_snapshot(snapshot)
    return submitted.strip() == str(snapshot["answer_mask"])
