"""Small read-only inputs for selecting a new task across first-part modes."""

from collections import Counter
from importlib import import_module
from itertools import islice
from typing import Any

from app.math.first_rotation import rank_families, topics


async def recent_issues(
    repository: Any, user_id: int, number: int
) -> list[tuple[str, str, str, bool]]:
    limit = 128 if number == 18 else 30
    pool = getattr(repository, "_pool", None)
    if pool is None:
        table = getattr(repository, "issued_history" if number == 6 else f"issued{number}", {})
        outcomes = getattr(repository, "outcomes" if number == 6 else f"outcomes{number}", {})
        order = getattr(repository, "issue_order", {})
        rows = [
            (
                order.get((user_id, pid), 0),
                row["family_id"],
                row["fingerprint"],
                outcomes.get(user_id, {}).get(pid, "issued"),
                False,
            )
            for pid, row in islice(reversed(table.get(user_id, {}).items()), limit)
        ]
        mixed = getattr(repository, "_mixed_training_records", {}).get(user_id, [])
        for i, row in enumerate(
            islice((r for r in reversed(mixed) if r["number"] == number), limit)
        ):
            rows.append(
                (
                    order.get((user_id, row.get("problem_id", row.get("id"))), -i),
                    row["family_id"],
                    row["fingerprint"],
                    row["outcome"],
                    True,
                )
            )
        rows.sort(key=lambda r: r[0], reverse=True)
        return [(f, fp, outcome, mix) for _, f, fp, outcome, mix in rows[:limit]]
    stored = await pool.fetch(
        """WITH learner AS (SELECT id FROM users WHERE telegram_user_id=$1),
        ordinary AS (SELECT p.family_id,p.fingerprint,p.outcome,false AS mix,p.issued_at,p.id
          FROM learner JOIN issued_problems p ON p.user_id=learner.id
          JOIN sessions s ON s.id=p.session_id WHERE s.mode=$2
          ORDER BY p.issued_at DESC,p.id DESC LIMIT $4),
        mixed AS (SELECT p.family_id,p.fingerprint,p.outcome,true AS mix,p.issued_at,p.id
          FROM learner JOIN mixed_training_sessions s ON s.user_id=learner.id
          JOIN mixed_training_problems p ON p.session_id=s.id WHERE p.number=$3
          ORDER BY p.issued_at DESC,p.id DESC LIMIT $4)
        SELECT family_id,fingerprint,outcome,mix FROM
          (SELECT * FROM ordinary UNION ALL SELECT * FROM mixed) h
          ORDER BY issued_at DESC,id DESC LIMIT $4""",
        user_id,
        f"task{number}",
        number,
        limit,
    )
    return [(r["family_id"], r["fingerprint"], r["outcome"], r["mix"]) for r in stored]


def enabled(number: int) -> list[str]:
    if number == 6:
        from app.math.registry import SPEC_BY_ID

        return list(SPEC_BY_ID)
    module = "oge07" if number == 7 else f"oge{number}"
    return list(import_module(f"app.math.{module}_scheduler").ENABLED_FAMILIES)


async def candidate_state(
    repository: Any,
    user_id: int,
    number: int,
    state: dict[str, object],
    *,
    for_mix: bool = False,
) -> dict[str, object]:
    recent = await recent_issues(repository, user_id, number)
    result = dict(state)
    if not recent:
        return result
    history = [f for f, _, _, _ in recent]
    outcomes = {f: status for f, _, status, _ in reversed(recent)}
    result["last_family_id"] = history[0]
    previous = state.get("family_queue")
    remaining = list(previous) if isinstance(previous, list) else []
    if number == 9:
        result["construction_history"] = history[:5]
    else:
        active = enabled(number)
        deck = list(dict.fromkeys([*(f for f in remaining if f in active), *active]))
        if number == 15:
            # The triangle trainer promises a complete tour of its 22 distinct constructions.
            unseen = [f for f in deck if f not in history[:len(active) - 1]]
            deck = unseen or deck
            # Consume larger topic groups while an alternating finish is still possible.
            counts = Counter(topics()[f] for f in deck)
            deck.sort(key=lambda f: -counts[topics()[f]])
        ranked = rank_families(
            deck, history, {f for f in remaining if outcomes.get(f) == "failed"}
        )
        if number in {16, 18} and len(history) < len(active):
            # Introduce every graphical family on the first tour. Keep fallback candidates
            # for finite/exhausted pools, including when continuing across modes.
            ranked.sort(key=lambda f: f in history)
        result["family_queue"] = ranked
    local = state.get("recent_fingerprints")
    local_fps = local if isinstance(local, list) else []
    if number == 16:
        result["other_mode_fingerprints"] = [fp for _, fp, _, mix in recent if mix != for_mix]
    else:
        result["recent_fingerprints"] = list(
            dict.fromkeys([*local_fps, *(fp for _, fp, _, _ in reversed(recent))])
        )
    return result


async def specialist_state(
    repository: Any, user_id: int, number: int, state: dict[str, object]
) -> dict[str, object]:
    prepared = await candidate_state(repository, user_id, number, state)
    selected = await repository.training_family(user_id, number)
    if selected is not None:
        prepared["selected_family_id"] = selected
        prepared["family_queue"] = [selected]
    return prepared


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
