"""Read-only cross-number insights from immutable issued tasks and accepted attempts."""
from __future__ import annotations

import json
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


# Select individual JSON scalars only: snapshots can contain multi-megabyte images.
_BASE = """
WITH tasks AS (
 SELECT p.id, p.user_id, p.family_id, p.outcome, p.hints_used,
        p.solution_viewed_at IS NOT NULL AS solution_viewed, p.issued_at,
        CASE WHEN s.mode ~ '^task[0-9]{1,2}$' THEN substring(s.mode from 5)::int
             WHEN p.family_id ~ '^OGE0?[0-9]{1,2}-'
               THEN substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int
             WHEN COALESCE(p.snapshot->>'exam_number', p.snapshot->>'number') ~ '^[0-9]{1,2}$'
               THEN COALESCE(p.snapshot->>'exam_number', p.snapshot->>'number')::int
             ELSE 0 END AS number
 FROM issued_problems p JOIN users u ON u.id=p.user_id
 LEFT JOIN sessions s ON s.id=p.session_id
 WHERE u.telegram_user_id=$1
), relevant AS (SELECT * FROM tasks WHERE number BETWEEN 6 AND 14)
"""
_METRIC_ROWS = """, metrics AS (
 SELECT p.number, p.family_id, 1::bigint AS issued, a.attempts,
        (p.outcome='solved')::int AS correct,
        (p.outcome='solved' AND a.correct_no=1)::int AS first_correct,
        (p.outcome='solved' AND a.correct_no=2)::int AS second_correct,
        (p.outcome='solved' AND a.used_hint IS FALSE)::int AS unassisted_correct,
        (p.outcome='solved' AND a.used_hint IS TRUE)::int AS assisted_correct,
        (p.outcome='solved' AND a.used_hint IS NULL)::int AS unknown_assistance,
        (p.outcome='solved' AND a.correct_no IS NULL)::int AS unknown_correct_attempt,
        (p.outcome='failed')::int AS failed, (p.outcome='skipped')::int AS skipped,
        COALESCE(p.hints_used,0) AS hints_used, p.solution_viewed::int AS solutions_viewed
 FROM relevant p CROSS JOIN LATERAL (
   SELECT count(*) AS attempts,
          (array_agg(attempt_no ORDER BY attempt_no) FILTER (WHERE is_correct))[1] AS correct_no,
          (array_agg(used_hint ORDER BY attempt_no) FILTER (WHERE is_correct))[1] AS used_hint
   FROM attempts WHERE problem_id=p.id AND user_id=p.user_id
 ) a
)
"""
_SUMS = ', '.join(f'COALESCE(sum({metric}),0)::bigint AS {metric}' for metric in METRICS)


def _page(page: str, page_size: int) -> tuple[str, int, int]:
    section, _, value = page.partition(":")
    if section not in {"summary", "numbers", "families", "history", "errors"}:
        section = "summary"
    return section, int(value) if value.isdigit() else 0, max(1, min(page_size, 6))


async def _postgres_insights(repository: Any, user_id: int, page: str,
                             page_size: int) -> dict[str, Any]:
    section, offset, limit = _page(page, page_size)
    result = summarize([])
    result.update(page_offset=offset, page_total=0, paginated=True)
    if section in {"summary", "numbers"}:
        rows = await repository._pool.fetch(
            _BASE + _METRIC_ROWS + f"SELECT number, {_SUMS} FROM metrics "
            "GROUP BY GROUPING SETS ((number), ())", user_id)
        for row in rows:
            values = {metric: row[metric] for metric in METRICS}
            if row["number"] is None:
                result["total"] = values
            else:
                result["numbers"][row["number"]] = values
        return result
    if section == "families":
        # Aggregate in PostgreSQL; transfer only the requested family page.
        result["page_total"] = await repository._pool.fetchval(
            _BASE + "SELECT count(*) FROM (SELECT number, family_id FROM relevant "
            "GROUP BY number, family_id) f", user_id)
        rows = await repository._pool.fetch(
            _BASE + _METRIC_ROWS + f"SELECT number, family_id, {_SUMS} FROM metrics "
            "GROUP BY number, family_id ORDER BY number, family_id LIMIT $2 OFFSET $3",
            user_id, limit, offset)
        result[section] = [{**dict(row), "name": family_name(row["family_id"])} for row in rows]
        return result
    predicate = (" WHERE EXISTS (SELECT 1 FROM attempts a WHERE a.problem_id=p.id "
                 "AND a.user_id=p.user_id AND NOT a.is_correct)") if section == "errors" else ""
    result["page_total"] = await repository._pool.fetchval(
        _BASE + "SELECT count(*) FROM relevant p" + predicate, user_id)
    rows = await repository._pool.fetch(
        _BASE + "SELECT p.id, p.number, p.family_id, p.outcome, p.issued_at, "
        "left(i.snapshot->>'condition', 120) AS condition FROM "
        "(SELECT p.* FROM relevant p" + predicate + " ORDER BY p.issued_at DESC, p.id DESC "
        "LIMIT $2 OFFSET $3) p JOIN issued_problems i ON i.id=p.id "
        "ORDER BY p.issued_at DESC, p.id DESC", user_id, limit, offset)
    result[section] = [{**dict(row), "family_name": family_name(row["family_id"])} for row in rows]
    return result


async def training_insights(repository: Any, telegram_user_id: int,
                            page: str = "summary", page_size: int = 6) -> dict[str, Any]:
    """Read-only projections: summaries never load history; list pages are bounded."""
    if hasattr(repository, "_pool"):
        return await _postgres_insights(repository, telegram_user_id, page, page_size)
    records: list[dict[str, Any]] = []
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
    result = summarize(records)
    section, offset, limit = _page(page, page_size)
    total = len(result.get(section, [])) if section in {"families", "history", "errors"} else 0
    if section in {"families", "history", "errors"}:
        if section == "families":
            result[section].sort(key=lambda row: (row["number"], row["family_id"]))
        result[section] = result[section][offset:offset + limit]
    if section != "history":
        result["history"] = []
    if section != "errors":
        result["errors"] = []
    result.update(page_offset=offset, page_total=total, paginated=True)
    return result
