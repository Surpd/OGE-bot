"""Read-only cross-number insights from immutable issued tasks and accepted attempts."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

NUMBERS = tuple(range(6, 15))
METRICS = ("issued", "attempts", "correct", "first_correct", "second_correct",
           "unassisted_correct", "assisted_correct", "unknown_assistance",
           "unknown_correct_attempt",
           "failed", "skipped", "hints_used", "solutions_viewed")


@lru_cache(maxsize=1)
def family_names() -> dict[str, str]:
    """Use the source registry names, including retained historical families."""
    names: dict[str, str] = {}
    atlas = Path(__file__).resolve().parents[2] / "atlas"

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            key = value.get("family_id", value.get("id"))
            name = value.get("name", value.get("title"))
            if isinstance(key, str) and isinstance(name, str):
                names[key] = name
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for path in (atlas / "atlas.json", *sorted(atlas.glob("oge*_reference_structures.json"))):
        visit(json.loads(path.read_text(encoding="utf-8")))
    names.update({
        "OGE08-R04": "Произведение квадратных корней",
        "OGE08-R08": "Квадрат суммы с квадратным корнем",
    })
    return names


def family_name(family: str) -> str:
    names = family_names()
    if family in names:
        return names[family]
    # Runtime generators may split a registry family into operation variants.
    prefixes = [key for key in names if family.startswith(key + "-")]
    return names[max(prefixes, key=len)] if prefixes else "Тип из прежней версии"


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = dict.fromkeys(METRICS, 0)
    numbers = {number: dict.fromkeys(METRICS, 0) for number in NUMBERS}
    families: dict[tuple[int, str], dict[str, Any]] = {}
    history = []
    for record in records:
        number = record["number"]
        if number not in numbers:
            continue
        family = str(record["family_id"])
        key = (number, family)
        bucket = families.setdefault(key, {
            **dict.fromkeys(METRICS, 0), "number": number, "family_id": family,
            "name": family_name(family),
        })
        attempts = record.get("attempt_records", [])
        outcome = record.get("outcome", "unknown")
        correct = outcome == "solved"
        successful = next((a for a in attempts if a.get("is_correct")), None)
        # Only the attempt-time flag proves whether a correct answer was assisted.
        used_hint = successful.get("used_hint") if successful else None
        metrics = {
            "issued": 1, "attempts": len(attempts), "correct": int(correct),
            "first_correct": int(correct and successful is not None
                                 and successful.get("attempt_no") == 1),
            "second_correct": int(correct and successful is not None
                                  and successful.get("attempt_no") == 2),
            "unassisted_correct": int(correct and used_hint is False),
            "assisted_correct": int(correct and used_hint is True),
            "unknown_assistance": int(correct and used_hint is None),
            "unknown_correct_attempt": int(correct and successful is None),
            "failed": int(outcome == "failed"), "skipped": int(outcome == "skipped"),
            "hints_used": int(record.get("hints_used") or 0),
            "solutions_viewed": int(bool(record.get("solution_viewed"))),
        }
        for target in (total, numbers[number], bucket):
            for metric, value in metrics.items():
                target[metric] += value
        history.append({**record, "family_name": bucket["name"],
                        "has_error": any(a.get("is_correct") is False for a in attempts)})
    return {"total": total, "numbers": numbers, "families": list(families.values()),
            "history": history, "errors": [r for r in history if r["has_error"]]}


async def training_insights(repository: Any, telegram_user_id: int) -> dict[str, Any]:
    """No writes: opening progress must preserve every paused training session."""
    records: list[dict[str, Any]] = []
    if hasattr(repository, "_pool"):
        rows = await repository._pool.fetch(
            """SELECT p.id, p.family_id, p.snapshot, p.outcome, p.hints_used,
                      p.solution_viewed_at IS NOT NULL AS solution_viewed, p.issued_at,
                      s.mode,
                      COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'attempt_no', a.attempt_no, 'is_correct', a.is_correct,
                        'used_hint', a.used_hint) ORDER BY a.attempt_no)
                        FROM attempts a WHERE a.problem_id=p.id AND a.user_id=p.user_id),
                        '[]'::jsonb) AS attempt_records
               FROM issued_problems p JOIN users u ON u.id=p.user_id
               LEFT JOIN sessions s ON s.id=p.session_id
               WHERE u.telegram_user_id=$1 ORDER BY p.issued_at DESC, p.id DESC""",
            telegram_user_id,
        )
        for row in rows:
            record = dict(row)
            mode = record.pop("mode")
            # A detached historical snapshot may still carry its original exam number.
            snapshot = record.pop("snapshot")
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            family_number = re.match(r"OGE0?(\d+)-", str(record["family_id"]))
            number = (int(mode[4:]) if mode and re.fullmatch(r"task\d+", mode)
                      else int(family_number.group(1)) if family_number
                      else snapshot.get("exam_number", snapshot.get("number", 0)))
            record["number"] = number
            record["condition"] = str(snapshot.get("condition", ""))
            if isinstance(record["attempt_records"], str):
                record["attempt_records"] = json.loads(record["attempt_records"])
            records.append(record)
    else:
        for number in NUMBERS:
            attrs = ("issued_history", "attempt_history", "outcomes", "hints_history",
                     "solutions_viewed") if number == 6 else (
                         f"issued{number}", f"attempts{number}", f"outcomes{number}",
                         f"hints{number}", f"solutions{number}")
            issued, attempts, outcomes, hints, solutions = (
                getattr(repository, attr, {}).get(telegram_user_id, {}) for attr in attrs)
            by_problem: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for attempt in attempts:
                by_problem[str(attempt["problem_id"])].append(attempt)
            for pid, snapshot in reversed(list(issued.items())):
                records.append({"id": pid, "number": number,
                                "family_id": snapshot.get("family_id", "unknown"),
                                "condition": snapshot.get("condition", ""),
                                "outcome": outcomes.get(pid, "unknown"),
                                "hints_used": hints.get(pid, 0),
                                "solution_viewed": pid in solutions,
                                "attempt_records": by_problem.get(str(pid), []),
                                "issued_at": None})
    return summarize(records)
