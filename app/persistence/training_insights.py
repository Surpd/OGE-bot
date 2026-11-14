"""Read-only cross-number insights from immutable issued tasks and accepted attempts."""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

NUMBERS = tuple(range(1, 15))
METRICS = ("issued", "completed", "attempts", "correct", "first_correct", "second_correct",
           "unassisted_correct", "assisted_correct", "unknown_assistance",
           "unknown_correct_attempt",
           "error_tasks", "failed", "skipped", "hints_used", "solutions_viewed")

_COMPLETED = frozenset({"solved", "failed", "skipped", "solution_viewed"})
_STORY_NAMES = {
    "TYRES": "Шины", "PAPER": "Бумага", "STOVE": "Печь", "TARIFF": "Тарифы",
    "GARDEN": "Участок", "FLAT": "Квартира", "ROUTE": "Маршрут",
}


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
    if family.startswith("OGE15:"):
        return _STORY_NAMES.get(family.partition(":")[2], "Практическое задание")
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
        has_error = any(a.get("is_correct") is False for a in attempts)
        # Only the attempt-time flag proves whether a correct answer was assisted.
        used_hint = successful.get("used_hint") if successful else None
        metrics = {
            "issued": 1, "completed": int(outcome in _COMPLETED),
            "attempts": len(attempts), "correct": int(correct),
            "first_correct": int(correct and successful is not None
                                 and successful.get("attempt_no") == 1),
            "second_correct": int(correct and successful is not None
                                  and successful.get("attempt_no") == 2),
            "unassisted_correct": int(correct and used_hint is False),
            "assisted_correct": int(correct and used_hint is True),
            "unknown_assistance": int(correct and used_hint is None),
            "unknown_correct_attempt": int(correct and successful is None),
            "error_tasks": int(has_error),
            "failed": int(outcome == "failed"), "skipped": int(outcome == "skipped"),
            "hints_used": int(record.get("hints_used") or 0),
            "solutions_viewed": int(bool(record.get("solution_viewed"))),
        }
        for target in (total, numbers[number], bucket):
            for metric, value in metrics.items():
                target[metric] += value
        history.append({**record, "family_name": bucket["name"], "has_error": has_error})
    return {"total": total, "numbers": numbers, "families": list(families.values()),
            "history": history, "errors": [r for r in history if r["has_error"]]}


# Projections below select scalar task fields only; snapshots may contain large content.
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
 SELECT p.number, p.family_id, 1::bigint AS issued,
        (p.outcome IN ('solved','failed','skipped','solution_viewed'))::int AS completed,
        a.attempts, (p.outcome='solved')::int AS correct,
        (p.outcome='solved' AND a.correct_no=1)::int AS first_correct,
        (p.outcome='solved' AND a.correct_no=2)::int AS second_correct,
        (p.outcome='solved' AND a.used_hint IS FALSE)::int AS unassisted_correct,
        (p.outcome='solved' AND a.used_hint IS TRUE)::int AS assisted_correct,
        (p.outcome='solved' AND a.used_hint IS NULL)::int AS unknown_assistance,
        (p.outcome='solved' AND a.correct_no IS NULL)::int AS unknown_correct_attempt,
        a.has_error::int AS error_tasks, (p.outcome='failed')::int AS failed,
        (p.outcome='skipped')::int AS skipped, COALESCE(p.hints_used,0) AS hints_used,
        p.solution_viewed::int AS solutions_viewed
 FROM relevant p CROSS JOIN LATERAL (
   SELECT count(*)::bigint AS attempts,
          (array_agg(attempt_no ORDER BY attempt_no) FILTER (WHERE is_correct))[1] AS correct_no,
          (array_agg(used_hint ORDER BY attempt_no) FILTER (WHERE is_correct))[1] AS used_hint,
          COALESCE(bool_or(NOT is_correct),false) AS has_error
   FROM attempts WHERE problem_id=p.id AND user_id=p.user_id
 ) a
)
"""
_SCENARIO_EVENTS = """, scenario_events AS (
 SELECT progress.session_id, session.scenario_id, progress.position::int AS number,
        'OGE15:' || scenario.story_code AS family_id, progress.status AS outcome,
        progress.hints_used, (progress.solution_viewed_at IS NOT NULL) AS solution_viewed,
        progress.updated_at
 FROM oge15_question_progress progress
 JOIN oge15_sessions session ON session.id=progress.session_id
 JOIN oge15_scenarios scenario ON scenario.id=session.scenario_id
 JOIN users app_user ON app_user.id=session.user_id
 WHERE app_user.telegram_user_id=$1 AND progress.status <> 'pending'
), scenario_attempts AS (
 SELECT attempt.session_id, attempt.position, count(*)::bigint AS attempts,
        (array_agg(attempt.attempt_no ORDER BY attempt.attempt_no)
          FILTER (WHERE attempt.is_correct))[1] AS correct_no,
        (array_agg(attempt.used_hint ORDER BY attempt.attempt_no)
          FILTER (WHERE attempt.is_correct))[1] AS used_hint,
        COALESCE(bool_or(NOT attempt.is_correct),false) AS has_error
 FROM oge15_attempts attempt
 JOIN oge15_sessions session ON session.id=attempt.session_id
 JOIN users app_user ON app_user.id=session.user_id
 WHERE app_user.telegram_user_id=$1 GROUP BY attempt.session_id, attempt.position
), scenario_metrics AS (
 SELECT event.number, event.family_id, 1::bigint AS issued,
        (event.outcome IN ('solved','failed','skipped','solution_viewed'))::int AS completed,
        COALESCE(attempt.attempts,0)::bigint AS attempts,
        (event.outcome='solved')::int AS correct,
        (event.outcome='solved' AND attempt.correct_no=1)::int AS first_correct,
        (event.outcome='solved' AND attempt.correct_no=2)::int AS second_correct,
        (event.outcome='solved' AND attempt.used_hint IS FALSE)::int AS unassisted_correct,
        (event.outcome='solved' AND attempt.used_hint IS TRUE)::int AS assisted_correct,
        (event.outcome='solved' AND attempt.used_hint IS NULL)::int AS unknown_assistance,
        (event.outcome='solved' AND attempt.correct_no IS NULL)::int AS unknown_correct_attempt,
        COALESCE(attempt.has_error,false)::int AS error_tasks,
        (event.outcome='failed')::int AS failed, (event.outcome='skipped')::int AS skipped,
        event.hints_used, (event.solution_viewed OR event.outcome='solution_viewed')::int
          AS solutions_viewed
 FROM scenario_events event LEFT JOIN scenario_attempts attempt
   ON attempt.session_id=event.session_id AND attempt.position=event.number
)
"""
_METRICS_SELECT = ', '.join(f'COALESCE(sum({metric}),0)::bigint AS {metric}' for metric in METRICS)


def _page(page: str, page_size: int) -> tuple[str, int, int]:
    section, _, value = page.partition(":")
    if section not in {"summary", "numbers", "families", "history", "errors", "number"}:
        section = "summary"
    return section, int(value) if value.isdigit() else 0, max(1, min(page_size, 6))


def _unified_metrics_cte() -> str:
    return (_BASE + _METRIC_ROWS + _SCENARIO_EVENTS + ", unified AS ("
            "SELECT * FROM metrics UNION ALL SELECT * FROM scenario_metrics)\n")


async def _postgres_insights(repository: Any, user_id: int, page: str,
                             page_size: int) -> dict[str, Any]:
    section, offset, limit = _page(page, page_size)
    result = summarize([])
    result.update(page_offset=offset, page_total=0, paginated=True)
    prefix = _unified_metrics_cte()
    if section in {"summary", "numbers", "number"}:
        rows = await repository._pool.fetch(
            prefix + f"SELECT number, {_METRICS_SELECT} FROM unified "
            "GROUP BY GROUPING SETS ((number), ())", user_id)
        for row in rows:
            values = {metric: int(row[metric]) for metric in METRICS}
            if row["number"] is None:
                result["total"] = values
            else:
                result["numbers"][int(row["number"])] = values
        if section == "number":
            result["selected_number"] = offset
        return result
    if section == "families":
        family_cte = (
            prefix + ", family_rows AS (SELECT number,family_id," + _METRICS_SELECT
            + " FROM unified GROUP BY number,family_id) "
        )
        result["page_total"] = await repository._pool.fetchval(
            family_cte + "SELECT count(*) FROM family_rows", user_id)
        rows = await repository._pool.fetch(
            family_cte + "SELECT * FROM family_rows ORDER BY number,family_id "
            "LIMIT $2 OFFSET $3", user_id, limit, offset)
        result[section] = [
            {**dict(row), "name": family_name(row["family_id"])} for row in rows
        ]
        return result
    history_cte = _BASE + _SCENARIO_EVENTS + ", history_rows AS ("
    history_cte += """
      SELECT 'o:'||p.id::text AS record_id, p.id, p.number, p.family_id, p.outcome,
             p.issued_at, left(i.snapshot->>'condition',160) AS condition,
             EXISTS (SELECT 1 FROM attempts a WHERE a.problem_id=p.id
                     AND a.user_id=p.user_id AND NOT a.is_correct) AS has_error
      FROM relevant p JOIN issued_problems i ON i.id=p.id
      UNION ALL
      SELECT 's:'||event.session_id::text||':'||event.number::text, NULL::uuid,
             event.number,event.family_id,event.outcome,event.updated_at,
             left(scenario.snapshot->'questions'->(event.number-1)->>'condition',160), EXISTS (
                 SELECT 1 FROM oge15_attempts a WHERE a.session_id=event.session_id
                   AND a.position=event.number AND NOT a.is_correct)
      FROM scenario_events event JOIN oge15_scenarios scenario
        ON scenario.id=event.scenario_id
    ) """
    where = " WHERE has_error" if section == "errors" else ""
    result["page_total"] = await repository._pool.fetchval(
        history_cte + "SELECT count(*) FROM history_rows" + where, user_id)
    rows = await repository._pool.fetch(
        history_cte + "SELECT * FROM history_rows" + where +
        " ORDER BY issued_at DESC,record_id DESC LIMIT $2 OFFSET $3",
        user_id, limit, offset)
    result[section] = [
        {**dict(row), "family_name": family_name(row["family_id"])} for row in rows
    ]
    return result


async def _memory_records(repository: Any, telegram_user_id: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number in range(6, 15):
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
            records.append({"id": pid, "record_id": f"o:{pid}", "number": number,
                            "family_id": snapshot.get("family_id", "unknown"),
                            "condition": snapshot.get("condition", ""),
                            "outcome": outcomes.get(pid, "issued"),
                            "hints_used": hints.get(pid, 0),
                            "solution_viewed": pid in solutions,
                            "attempt_records": by_problem.get(str(pid), []),
                            "issued_at": None})
    return records


async def training_insights(repository: Any, telegram_user_id: int,
                            page: str = "summary", page_size: int = 6) -> dict[str, Any]:
    """Read-only, user-scoped summary and bounded history across all available numbers."""
    if hasattr(repository, "_pool"):
        return await _postgres_insights(repository, telegram_user_id, page, page_size)
    result = summarize(await _memory_records(repository, telegram_user_id))
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
    if section == "number":
        result["selected_number"] = offset
    result.update(page_offset=offset, page_total=total, paginated=True)
    return result


async def training_record_detail(repository: Any, telegram_user_id: int,
                                 record_id: str) -> dict[str, Any] | None:
    """Fetch one task's visible condition and attempt outcomes, always owner-scoped."""
    if hasattr(repository, "_pool"):
        from uuid import UUID

        parts = record_id.split(":")
        if len(parts) == 2 and parts[0] == "o":
            try:
                problem_id = UUID(parts[1])
            except ValueError:
                return None
            row = await repository._pool.fetchrow(
                """SELECT '№'||CASE WHEN p.family_id ~ '^OGE0?[0-9]{1,2}-'
                     THEN substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int
                     ELSE 0 END AS number,p.family_id,p.outcome,p.issued_at,
                     left(p.snapshot->>'condition',200) AS condition
                   FROM issued_problems p JOIN users u ON u.id=p.user_id
                   WHERE u.telegram_user_id=$1 AND p.id=$2""", telegram_user_id, problem_id)
            if row is None:
                return None
            attempts = await repository._pool.fetch(
                """SELECT attempt_no,is_correct,used_hint FROM attempts a JOIN users u
                     ON u.id=a.user_id JOIN issued_problems p ON p.user_id=u.id
                     AND p.id=a.problem_id WHERE u.telegram_user_id=$1 AND p.id=$2
                   ORDER BY attempt_no""", telegram_user_id, problem_id)
        elif len(parts) == 3 and parts[0] == "s" and parts[2].isdigit():
            try:
                session_id = UUID(parts[1])
            except ValueError:
                return None
            position = int(parts[2])
            if position not in range(1, 6):
                return None
            row = await repository._pool.fetchrow(
                """SELECT '№1–5 · '||scenario.story_code||' · №'||progress.position AS number,
                     'OGE15:'||scenario.story_code AS family_id,progress.status AS outcome,
                     progress.updated_at AS issued_at,
                     left(scenario.snapshot->'questions'->(progress.position-1)->>'condition',200)
                       AS condition
                   FROM oge15_question_progress progress
                   JOIN oge15_sessions session ON session.id=progress.session_id
                   JOIN oge15_scenarios scenario ON scenario.id=session.scenario_id
                   JOIN users app_user ON app_user.id=session.user_id
                   WHERE app_user.telegram_user_id=$1 AND session.id=$2
                     AND progress.position=$3 AND progress.status <> 'pending'""",
                telegram_user_id, session_id, position)
            if row is None:
                return None
            attempts = await repository._pool.fetch(
                """SELECT attempt_no,is_correct,used_hint FROM oge15_attempts
                   WHERE session_id=$1 AND position=$2 ORDER BY attempt_no""",
                session_id, position)
        else:
            return None
        return {**dict(row), "attempt_records": [dict(attempt) for attempt in attempts]}

    for record in await _memory_records(repository, telegram_user_id):
        if record.get("record_id") == record_id:
            return record
    return None
