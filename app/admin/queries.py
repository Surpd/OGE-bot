"""Parameterized report queries over the restricted analytics projections."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.persistence.part2_budget_sql import BUDGET_ROWS, BUDGET_TOTALS, UTC_MONTH

PAGE_SIZE = 6
MIN_RANK_SAMPLE = 10
EXCLUDED = """excluded AS MATERIALIZED (
    SELECT user_id FROM accounts WHERE identity_key = ANY($3::text[])
)"""
LEARNER = "user_id NOT IN (SELECT user_id FROM excluded)"
IN_PERIOD = "created_at >= $1 AND created_at < $2"
MODE_EVENTS = f"""
    SELECT user_id,source,task_key,mode,created_at,false AS written
    FROM attempts WHERE {IN_PERIOD} AND {LEARNER}
    UNION ALL
    SELECT user_id,'written',issue_id::text,'written',created_at,true
    FROM written_checks WHERE {IN_PERIOD} AND {LEARNER}
"""

HOME = f"""
WITH {EXCLUDED},
active AS MATERIALIZED (
    SELECT user_id, min(created_at) first_event, max(created_at) last_event
    FROM activity WHERE {IN_PERIOD} AND {LEARNER} GROUP BY user_id
),
totals AS (
    SELECT count(*) attempts, count(DISTINCT (source,task_key)) answered
    FROM activity WHERE {IN_PERIOD} AND {LEARNER} AND source<>'written'
),
written AS (
    SELECT count(*) FILTER (WHERE status='graded') graded,
           count(*) FILTER (WHERE status='error') errors
    FROM written_checks WHERE {IN_PERIOD} AND {LEARNER}
),
fees AS (
    SELECT CASE WHEN count(*)=0 THEN 0 ELSE sum(cost_usd) END known_cost,
           count(*) FILTER (WHERE cost_usd IS NULL) unknown_cost
    FROM charges WHERE coalesce(dispatched_at,created_at) >= $1
        AND coalesce(dispatched_at,created_at) < $2
)
SELECT (SELECT count(*) FROM accounts WHERE {LEARNER}) registered,
       (SELECT count(*) FROM active) active,
       (SELECT count(*) FROM active a WHERE NOT EXISTS (
          SELECT FROM activity p WHERE p.user_id=a.user_id AND p.created_at < $1
       )) first,
       (SELECT count(*) FROM active WHERE (first_event AT TIME ZONE 'Europe/Moscow')::date
           < (last_event AT TIME ZONE 'Europe/Moscow')::date) repeat_days,
       totals.*, written.*, fees.*
FROM totals CROSS JOIN written CROSS JOIN fees
"""

DAYS = f"""
WITH {EXCLUDED}, counts AS (
    SELECT (created_at AT TIME ZONE 'Europe/Moscow')::date AS day, count(DISTINCT user_id) active
    FROM activity WHERE {IN_PERIOD} AND {LEARNER} GROUP BY 1
),
bounds AS (
    SELECT ($1::timestamptz AT TIME ZONE 'Europe/Moscow')::date start_day,
           (($2::timestamptz - interval '1 microsecond') AT TIME ZONE 'Europe/Moscow')::date end_day
)
SELECT start_day+i AS day, coalesce(counts.active,0) active
FROM bounds CROSS JOIN LATERAL generate_series(0,end_day-start_day) AS i
LEFT JOIN counts ON counts.day=start_day+i ORDER BY day
"""

MODES = f"""
WITH {EXCLUDED}, events AS ({MODE_EVENTS})
SELECT mode, count(DISTINCT user_id) users,
       count(DISTINCT (source,task_key)) FILTER (WHERE NOT written) answered,
       count(*) FILTER (WHERE NOT written) attempts,
       count(*) FILTER (WHERE written) submitted
FROM events GROUP BY mode ORDER BY users DESC, mode
"""

RETENTION = f"""
WITH {EXCLUDED},
candidates AS (
    SELECT user_id, (min(created_at) AT TIME ZONE 'Europe/Moscow')::date first_day
    FROM activity WHERE {IN_PERIOD} AND {LEARNER} GROUP BY user_id
),
cohort AS (
    SELECT c.* FROM candidates c WHERE NOT EXISTS (
        SELECT FROM activity p WHERE p.user_id=c.user_id AND p.created_at < $1
    )
)
SELECT count(*) eligible, count(*) FILTER (WHERE EXISTS (
    SELECT FROM activity a WHERE a.user_id=c.user_id
      AND a.created_at >= ((c.first_day + 7)::timestamp AT TIME ZONE 'Europe/Moscow')
      AND a.created_at < ((c.first_day + 14)::timestamp AT TIME ZONE 'Europe/Moscow')
)) returned FROM cohort c
"""

LEARNERS = f"""
WITH {EXCLUDED}
SELECT user_id, max(created_at) last_activity FROM activity
WHERE {IN_PERIOD} AND {LEARNER}
GROUP BY user_id ORDER BY last_activity DESC,user_id LIMIT $4 OFFSET $5
"""

LEARNER_CARD = f"""
WITH {EXCLUDED},
learner AS (
    SELECT user_id FROM accounts WHERE user_id=$4::uuid AND {LEARNER}
),
activity_totals AS (
    SELECT max(created_at) last_activity,
           count(DISTINCT (created_at AT TIME ZONE 'Europe/Moscow')::date) days
    FROM activity JOIN learner USING(user_id) WHERE {IN_PERIOD}
),
short_answers AS MATERIALIZED (
    SELECT source,task_key,number,correct FROM attempts JOIN learner USING(user_id)
    WHERE {IN_PERIOD}
),
written AS MATERIALIZED (
    SELECT number,status,score FROM written_checks JOIN learner USING(user_id) WHERE {IN_PERIOD}
)
SELECT EXISTS (SELECT FROM learner) found, activity_totals.*,
       (SELECT count(DISTINCT (source,task_key)) FROM short_answers) answered,
       (SELECT count(DISTINCT (source,task_key)) FROM short_answers WHERE correct) solved,
       (SELECT count(*) FROM written) submitted,
       (SELECT count(*) FROM written WHERE status='graded') graded,
       (SELECT sum(score) FROM written WHERE status='graded') points,
       ARRAY(SELECT number FROM short_answers UNION SELECT number FROM written ORDER BY 1) numbers
FROM activity_totals
"""

TASKS = f"""
WITH {EXCLUDED}, answers AS (
    SELECT number,count(DISTINCT user_id) users,
           count(DISTINCT (source,task_key)) answered,
           count(DISTINCT (source,task_key)) FILTER (WHERE correct) solved
    FROM attempts WHERE {IN_PERIOD} AND {LEARNER} AND source <> 'replay'
    GROUP BY number
)
SELECT n AS number, coalesce(answers.users,0) users,
       coalesce(answers.answered,0) answered, coalesce(answers.solved,0) solved
FROM generate_series(1,19) AS n LEFT JOIN answers ON answers.number=n ORDER BY n
"""

# An exposure can be confirmed by one positive observation. A negative classification
# requires every observed attempt on that task to have known negative evidence.
ANSWER_FACTS = """
    SELECT source, task_key, user_id, family_id,
           bool_or(correct) solved,
           bool_or(correct AND attempt_no=1) first_correct,
           bool_or(correct AND assisted IS FALSE) unassisted,
           bool_or(correct AND attempt_no=1 AND assisted IS FALSE) first_unassisted,
           bool_or(correct AND attempt_no=1 AND assisted IS FALSE AND novel IS TRUE)
             novel_first_unassisted,
           bool_or(correct AND attempt_no=1 AND assisted IS FALSE AND novel IS NULL)
             novelty_unknown,
           bool_or(correct AND assisted IS NULL) assistance_unknown,
           bool_or(assisted IS TRUE) OR bool_and(assisted IS NOT NULL) assistance_known,
           bool_or(hinted IS TRUE) hinted,
           bool_or(hinted IS TRUE) OR bool_and(hinted IS NOT NULL) hint_known,
           bool_or(NOT correct AND (attempt_no > 1 OR source='replay')) repeat_error
    FROM attempts WHERE {period} AND {learner} AND {selection}
    GROUP BY source,task_key,user_id,family_id
"""
TASK_TOTALS = """
    count(DISTINCT user_id) users, count(*) answered,
    count(*) FILTER (WHERE solved) solved, count(*) FILTER (WHERE first_correct) first_correct,
    count(*) FILTER (WHERE unassisted) unassisted,
    count(*) FILTER (WHERE first_unassisted) first_unassisted,
    count(*) FILTER (WHERE novel_first_unassisted) novel_first_unassisted,
    count(*) FILTER (WHERE novelty_unknown) novelty_unknown,
    count(*) FILTER (WHERE assistance_unknown) assistance_unknown,
    count(*) FILTER (WHERE assistance_known) assistance_known,
    count(*) FILTER (WHERE hinted) hinted,
    count(*) FILTER (WHERE hint_known) hint_known,
    count(*) FILTER (WHERE repeat_error) repeat_errors
"""

TYPE_ORDERS = {
    "sample": "answered DESC,family_id",
    "success": f"""CASE WHEN answered >= {MIN_RANK_SAMPLE}
                    THEN solved::numeric / nullif(answered,0) END ASC NULLS LAST,
                    answered DESC,family_id""",
    "help": f"""CASE WHEN hint_known >= {MIN_RANK_SAMPLE}
                 THEN hinted::numeric / nullif(hint_known,0) END DESC NULLS LAST,
                 answered DESC,family_id""",
}
TYPES = f"""
WITH {EXCLUDED}, answers AS MATERIALIZED (
    SELECT source,task_key,user_id,family_id,bool_or(correct) solved,
           bool_or(hinted IS TRUE) hinted,
           bool_or(hinted IS TRUE) OR bool_and(hinted IS NOT NULL) hint_known,
           bool_or(assisted IS TRUE) OR bool_and(assisted IS NOT NULL) assistance_known
    FROM attempts WHERE {IN_PERIOD} AND {LEARNER} AND number=$4 AND source<>'replay'
    GROUP BY source,task_key,user_id,family_id
), families AS (
    SELECT family_id FROM answers
    UNION
    SELECT family_id FROM tasks WHERE number=$4 AND {LEARNER} AND source<>'replay'
        AND issued_at >= $1 AND issued_at < $2
), report AS (
    SELECT family_id, count(DISTINCT user_id) users, count(*) answered,
           count(*) FILTER (WHERE solved) solved, count(*) FILTER (WHERE hinted) hinted,
           count(*) FILTER (WHERE hint_known) hint_known,
           count(*) FILTER (WHERE assistance_known) assistance_known
    FROM answers GROUP BY family_id
)
SELECT families.family_id, coalesce(users,0) users, coalesce(answered,0) answered,
       coalesce(solved,0) solved,coalesce(hinted,0) hinted,
       coalesce(assistance_known,0) assistance_known, coalesce(hint_known,0) hint_known
FROM families LEFT JOIN report USING(family_id)
ORDER BY {{order}} LIMIT $5 OFFSET $6
"""

DETAIL_ANSWERS = ANSWER_FACTS.format(
    period=IN_PERIOD, learner=LEARNER, selection="number=$4 AND family_id=$5"
)
TASK = f"""
WITH {EXCLUDED}, answers AS MATERIALIZED ({DETAIL_ANSWERS}),
actions AS (
    SELECT count(*) FILTER (WHERE issued_at >= $1 AND issued_at < $2) issued,
           count(*) FILTER (WHERE skipped_at >= $1 AND skipped_at < $2) skipped,
           count(*) FILTER (WHERE solution_at >= $1 AND solution_at < $2) solution_views
    FROM tasks WHERE number=$4 AND family_id=$5 AND source <> 'replay' AND {LEARNER}
        AND ((issued_at >= $1 AND issued_at < $2) OR (skipped_at >= $1 AND skipped_at < $2)
             OR (solution_at >= $1 AND solution_at < $2))
),
primary_answers AS (
    SELECT {TASK_TOTALS} FROM answers WHERE source<>'replay'
),
replays AS (
    SELECT count(*) replay_answered, count(*) FILTER (WHERE solved) replay_solved
    FROM answers WHERE source='replay'
)
SELECT primary_answers.*,actions.*,replays.* FROM primary_answers CROSS JOIN actions CROSS JOIN replays
"""  # noqa: E501

REPLAYS = f"""
WITH {EXCLUDED}
SELECT number,family_id,count(DISTINCT task_key) answered,
       count(DISTINCT task_key) FILTER (WHERE correct) solved,
       count(DISTINCT task_key) FILTER (WHERE NOT correct) repeat_errors
FROM attempts WHERE {IN_PERIOD} AND {LEARNER} AND source='replay'
GROUP BY number,family_id ORDER BY answered DESC,number,family_id LIMIT $4 OFFSET $5
"""

WRITTEN_COHORT = f"""
    SELECT * FROM written_checks WHERE {IN_PERIOD} AND {LEARNER} AND ($4=0 OR number=$4)
"""
WRITTEN = f"""
WITH {EXCLUDED}, cohort AS ({WRITTEN_COHORT})
SELECT (SELECT count(*) FROM written_issues WHERE {LEARNER} AND ($4=0 OR number=$4)
             AND issued_at >= $1 AND issued_at < $2) issued,
       count(DISTINCT issue_id) issues_submitted, count(*) submitted,
       count(*) FILTER (WHERE EXISTS (
           SELECT FROM written_checks earlier WHERE earlier.issue_id=c.issue_id
               AND earlier.revision < c.revision
       )) revisions,
       count(*) FILTER (WHERE status='graded') graded,
       count(*) FILTER (WHERE status='unreadable') unreadable,
       count(*) FILTER (WHERE status='uncertain') uncertain,
       count(*) FILTER (WHERE status='error') error,
       count(*) FILTER (WHERE status='pending') pending
FROM cohort c
"""

WRITTEN_DISTRIBUTION = f"""
WITH {EXCLUDED}, cohort AS ({WRITTEN_COHORT})
SELECT number, CASE WHEN $4<>0 THEN subtype_id END subtype_id,
       CASE WHEN $4<>0 THEN title END title,
       count(*) submitted, count(*) FILTER (WHERE status='graded') graded,
       count(*) FILTER (WHERE score=0 AND status='graded') zero,
       count(*) FILTER (WHERE score=1 AND status='graded') one,
       count(*) FILTER (WHERE score=2 AND status='graded') two
FROM cohort GROUP BY 1,2,3 ORDER BY 1,3,2 LIMIT $5 OFFSET $6
"""

COST = f"""
WITH {EXCLUDED},
reports AS (
    SELECT CASE WHEN count(*)=0 THEN 0 ELSE sum(cost_usd) END known_cost,
           count(*) FILTER (WHERE cost_usd IS NULL) unknown_cost,
           count(*) FILTER (WHERE diagnostic AND (
               dispatched_at IS NOT NULL OR cost_usd > 0
               OR status IN ('graded','unreadable','uncertain')
           )) diagnostics,
           CASE WHEN count(*) FILTER (WHERE diagnostic)=0 THEN 0
             ELSE sum(cost_usd) FILTER (WHERE diagnostic) END diagnostic_cost,
           count(*) FILTER (WHERE diagnostic AND cost_usd IS NULL) diagnostic_unknown
    FROM charges WHERE coalesce(dispatched_at,created_at) >= $1
        AND coalesce(dispatched_at,created_at) < $2
),
budget AS (
    SELECT {BUDGET_TOTALS}, {UTC_MONTH} month_start,
           (({UTC_MONTH} AT TIME ZONE 'UTC') + interval '1 month') AT TIME ZONE 'UTC' month_end
    FROM charges WHERE {BUDGET_ROWS}
),
results AS (
    SELECT count(*) FILTER (WHERE status='graded') graded,
           sum(cost_usd) written_cost, count(*) FILTER (WHERE cost_usd IS NULL) unknown_written
    FROM written_checks WHERE {IN_PERIOD} AND {LEARNER}
)
SELECT reports.*,budget.*,results.* FROM reports CROSS JOIN budget CROSS JOIN results
"""

SYSTEM_ERRORS = f"""
WITH {EXCLUDED}
SELECT count(*) FROM written_checks WHERE {IN_PERIOD} AND {LEARNER} AND status='error'
"""
OPERATIONS = """
SELECT status,count(*) FROM operations WHERE claimed_at >= $1 AND claimed_at < $2
    AND bot_id IN (0,$3) GROUP BY status ORDER BY status
"""


def page(rows: list[asyncpg.Record]) -> dict[str, Any]:
    return {"rows": [dict(row) for row in rows[:PAGE_SIZE]], "more": len(rows) > PAGE_SIZE}


def cost_report(values: Mapping[str, Any], budget: Decimal) -> dict[str, Any]:
    cost = values["written_cost"]
    graded = values["graded"]
    return {
        **values,
        "budget": budget,
        "available": max(Decimal(0), budget - values["spent"] - values["held"]),
        "known_cost_per_result": cost / graded if cost is not None and graded else None,
    }


class ReportQueries:
    def __init__(self, conn: asyncpg.Connection, args: tuple[Any, ...]) -> None:
        self.conn = conn
        self.args = args

    async def one(self, sql: str, *extra: object) -> dict[str, Any]:
        row = await self.conn.fetchrow(sql, *self.args, *extra)
        assert row is not None
        return dict(row)

    async def many(self, sql: str, *extra: object) -> list[asyncpg.Record]:
        return list(await self.conn.fetch(sql, *self.args, *extra))

    async def load(
        self, view: str, number: int, key: str, sort: str, offset: int,
        *, primary_id: int, budget: Decimal,
    ) -> dict[str, Any]:
        bounds = (PAGE_SIZE + 1, offset)
        match view:
            case "home" | "usage":
                return await self.one(HOME)
            case "learners":
                return page(await self.many(LEARNERS, *bounds))
            case "learner":
                return await self.one(LEARNER_CARD, UUID(key))
            case "tasks":
                return {"rows": [dict(row) for row in await self.many(TASKS)]}
            case "types":
                return page(await self.many(TYPES.format(order=TYPE_ORDERS[sort]), number, *bounds))
            case "task":
                return await self.one(TASK, number, key)
            case "replays":
                return page(await self.many(REPLAYS, *bounds))
            case "written":
                summary = await self.one(WRITTEN, number)
                return {**summary, **page(await self.many(WRITTEN_DISTRIBUTION, number, *bounds))}
            case "cost":
                return cost_report(await self.one(COST), budget)
            case "system":
                return {
                    "errors": await self.conn.fetchval(SYSTEM_ERRORS, *self.args),
                    "operations": [
                        dict(row) for row in await self.conn.fetch(
                            OPERATIONS, *self.args[:2], primary_id
                        )
                    ],
                }
            case _:
                raise ValueError("Unknown admin report")
