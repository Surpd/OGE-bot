"""Small read-only inputs for selecting a new task across first-part modes."""

from collections.abc import Iterator
from itertools import islice
from typing import Any

from app.math.first_rotation import rotate_tail


async def other_mode_recent(
    repository: Any,
    user_id: int,
    number: int,
    *,
    for_mix: bool,
) -> list[tuple[str, str, str]]:
    pool = getattr(repository, "_pool", None)
    if pool is None:
        rows: Iterator[Any]
        if for_mix:
            table = getattr(repository, "issued_history" if number == 6 else f"issued{number}", {})
            outcomes = getattr(repository, "outcomes" if number == 6 else f"outcomes{number}", {})
            user_outcomes = outcomes.get(user_id, {})
            return [
                (row["family_id"], row["fingerprint"], user_outcomes.get(pid, "issued"))
                for pid, row in islice(reversed(table.get(user_id, {}).items()), 8)
            ]
        else:
            mixed = getattr(repository, "_mixed_training_records", {}).get(user_id, [])
            rows = (row for row in reversed(mixed) if row["number"] == number)
        return [(row["family_id"], row["fingerprint"], row["outcome"]) for row in islice(rows, 8)]
    if for_mix:
        stored = await pool.fetch(
            """SELECT p.family_id, p.fingerprint, p.outcome FROM issued_problems p
               JOIN users u ON u.id=p.user_id JOIN sessions s ON s.id=p.session_id
               WHERE u.telegram_user_id=$1 AND s.mode=$2
               ORDER BY p.issued_at DESC,p.id DESC LIMIT 8""",
            user_id,
            f"task{number}",
        )
    else:
        stored = await pool.fetch(
            """SELECT p.family_id, p.fingerprint, p.outcome FROM mixed_training_problems p
               JOIN mixed_training_sessions s ON s.id=p.session_id JOIN users u ON u.id=s.user_id
               WHERE u.telegram_user_id=$1 AND p.number=$2
               ORDER BY p.issued_at DESC,p.id DESC LIMIT 8""",
            user_id,
            number,
        )
    return [(row["family_id"], row["fingerprint"], row["outcome"]) for row in stored]


async def candidate_state(
    repository: Any,
    user_id: int,
    number: int,
    state: dict[str, object],
    *,
    for_mix: bool = False,
) -> dict[str, object]:
    recent = await other_mode_recent(repository, user_id, number, for_mix=for_mix)
    result = dict(state)
    outcomes = {family: outcome for family, _, outcome in reversed(recent)}
    rotate_tail(
        number,
        result,
        recent[0][0] if recent else None,
        {family for family, outcome in outcomes.items() if outcome == "failed"},
    )
    if not recent:
        return result
    if not result.get("last_family_id"):
        result["last_family_id"] = recent[0][0]
    local = state.get("recent_fingerprints")
    local_fps = local if isinstance(local, list) else []
    # For finite circle pools the transaction verifies the cycle against its own
    # history. External fingerprints are preferences, never proof of exhaustion.
    if number == 16:
        result["other_mode_fingerprints"] = [fp for _, fp, _ in recent]
    else:
        result["recent_fingerprints"] = list(
            dict.fromkeys(
                [
                    *(fp for _, fp, _ in reversed(recent)),
                    *local_fps,
                ]
            )
        )
    return result


async def recent_story_families(repository: Any, user_id: int) -> list[str]:
    """Newest first. Pending positions have never been issued."""
    pool = getattr(repository, "_pool", None)
    if pool is None:
        records = getattr(repository, "_mixed_training_records", {}).get(user_id, [])
        return list(islice((r["family_id"] for r in reversed(records) if r["number"] <= 5), 30))
    rows = await pool.fetch(
        """WITH learner AS (SELECT id FROM users WHERE telegram_user_id=$1),
        practice AS (
            SELECT sc.snapshot->'questions'->(q.position::int-1)->>'family_id' AS family,
                   s.started_at AS issued, s.id, q.position
              FROM learner JOIN oge15_sessions s ON s.user_id=learner.id
              JOIN oge15_scenarios sc ON sc.id=s.scenario_id
              JOIN oge15_question_progress q ON q.session_id=s.id
              WHERE q.status <> 'pending'
              ORDER BY s.started_at DESC,s.id DESC,q.position DESC LIMIT 30
        ), mixed AS (
            SELECT p.family_id,p.issued_at,p.id,p.number FROM learner
              JOIN mixed_training_sessions s ON s.user_id=learner.id
              JOIN mixed_training_problems p ON p.session_id=s.id WHERE p.number <= 5
              ORDER BY p.issued_at DESC,p.id DESC LIMIT 30
        )
        SELECT family FROM (SELECT * FROM practice UNION ALL SELECT * FROM mixed) h
        WHERE family IS NOT NULL ORDER BY issued DESC,id DESC,position DESC LIMIT 30""",
        user_id,
    )
    return [r["family"] for r in rows]
