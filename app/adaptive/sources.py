"""Read compact facts for one changed source record in the learner's own schema."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from app.math.scenario_engine import ScenarioSnapshot
from app.math.scenarios.recent_questions import question_signature


@dataclass(frozen=True)
class Fact:
    at: datetime
    outcome: str
    ordinal: int
    attempt: int = 0
    assisted: bool | None = None
    score: int | None = None
    grade_status: str | None = None
    used_hint: bool | None = None
    solution_before: bool | None = None


@dataclass(frozen=True)
class Item:
    number: int
    skill: str
    variant: str
    source: str
    task: str
    facts: list[Fact]


def scenario_variant(scene: ScenarioSnapshot, number: int) -> str:
    signature = question_signature(scene, scene.questions[number - 1])
    return hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()


async def item(conn: asyncpg.Connection, owner: UUID, source: str, task: str) -> Item | None:
    if source == "written":
        return await _written(conn, owner, int(task))
    if source == "replay":
        row = await conn.fetchrow(
            """SELECT source_type,source_id,source_position,status,finished_at
               FROM training_error_replays WHERE user_id=$1 AND id=$2""",
            owner,
            UUID(task),
        )
        if not row or not row["finished_at"]:
            return None
        ref = str(row["source_id"])
        if row["source_type"] == "scenario":
            ref += f":{row['source_position']}"
        original = await item(conn, owner, row["source_type"], ref)
        if not original:
            return None
        return Item(
            original.number,
            original.skill,
            original.variant,
            source,
            task,
            [Fact(row["finished_at"], "replay", 1)],
        )
    args: tuple[object, ...]
    if source == "scenario":
        uid, pos = task.split(":")
        args = (owner, UUID(uid), int(pos))
        row = await conn.fetchrow(
            """SELECT sc.snapshot->'questions'->($3::int-1)->>'family_id' family_id,
               sc.snapshot AS scene,
               $3::int number,coalesce(p.adaptive_issued_at,s.started_at) issued_at,
               p.status outcome,
               p.solution_viewed_at,
               '' fingerprint FROM oge15_sessions s JOIN oge15_scenarios sc ON sc.id=s.scenario_id
               JOIN oge15_question_progress p ON p.session_id=s.id AND p.position=$3
               WHERE s.user_id=$1 AND s.id=$2 AND p.status<>'pending'""",
            *args,
        )
        attempt_sql = """SELECT a.* FROM oge15_attempts a JOIN oge15_sessions s ON s.id=a.session_id
                         WHERE s.user_id=$1 AND a.session_id=$2 AND a.position=$3"""
    else:
        args = (owner, UUID(task))
        if source == "ordinary":
            row = await conn.fetchrow(
                """SELECT p.family_id,p.fingerprint,p.outcome,p.solution_viewed_at,p.issued_at,
                   COALESCE(substring(p.family_id from '^OGE0?([0-9]{1,2})-')::int,
                   substring(s.mode from '^task([0-9]+)$')::int,
                   substring(p.snapshot->>'number' from '^([1-5])$')::int,0) number,
                   CASE WHEN p.family_id !~ '^OGE' THEN p.snapshot->'scenario_snapshot' END scene,
                   EXISTS(SELECT FROM adaptive_slots a WHERE a.problem=p.id) personal
                   FROM issued_problems p LEFT JOIN sessions s ON s.id=p.session_id
                   WHERE p.user_id=$1 AND p.id=$2""",
                *args,
            )
            attempt_sql = "SELECT * FROM attempts WHERE user_id=$1 AND problem_id=$2"
        else:
            row = await conn.fetchrow(
                """SELECT p.family_id,p.fingerprint,p.outcome,p.solution_viewed_at,p.issued_at,
                   p.number,CASE WHEN p.number<=5 THEN
                   (SELECT first.snapshot->'_original_scenario_snapshot'
                    FROM mixed_training_problems first
                    WHERE first.session_id=p.session_id AND first.number=1
                    AND first.fingerprint=regexp_replace(p.fingerprint,':[1-5]$',':1')
                    AND first.issued_at<=p.issued_at ORDER BY first.issued_at DESC LIMIT 1)
                   END scene
                   FROM mixed_training_problems p JOIN mixed_training_sessions s
                   ON s.id=p.session_id WHERE s.user_id=$1 AND p.id=$2""",
                *args,
            )
            attempt_sql = """SELECT a.* FROM mixed_training_attempts a
                JOIN mixed_training_problems p ON p.id=a.problem_id
                JOIN mixed_training_sessions s ON s.id=p.session_id
                WHERE s.user_id=$1 AND p.id=$2"""
    if not row or not row["family_id"] or row["number"] not in range(1, 20):
        return None
    family = row["family_id"]
    variant = row["fingerprint"]
    if row["number"] <= 5:
        try:
            scene = ScenarioSnapshot.from_snapshot(json.loads(row["scene"] or "{}"))
            variant = scenario_variant(scene, row["number"])
        except (ValueError, KeyError, TypeError):
            variant = ""
    elif variant == task:
        variant = ""
    facts = [Fact(row["issued_at"], "issued", 0)]
    for a in await conn.fetch(attempt_sql + " ORDER BY attempt_no", *args):
        at = a["created_at"]
        helped = a["used_hint"] if a["telegram_message_id"] is not None else None
        solution = bool(row["solution_viewed_at"] and row["solution_viewed_at"] <= at)
        facts.append(
            Fact(
                at,
                "correct" if a["is_correct"] else "wrong",
                a["attempt_no"],
                a["attempt_no"],
                True if solution else helped,
                used_hint=helped,
                solution_before=solution,
            )
        )
    if row["solution_viewed_at"] and row["outcome"] == "solution_viewed":
        facts.append(Fact(row["solution_viewed_at"], "solution", 100))
    if row["outcome"] == "skipped":
        facts.append(Fact(facts[-1].at, "skip", 101))
    return Item(
        row["number"], family, variant, "personal" if row.get("personal") else source, task, facts
    )


async def _written(conn: asyncpg.Connection, owner: UUID, issue: int) -> Item | None:
    row = await conn.fetchrow(
        """SELECT i.number,i.subtype_id,i.task_id,i.hints,i.repeat_kind,i.issued_at,
           i.solution_viewed_at,v.reviewed FROM part2_issues i
           JOIN users u ON u.telegram_user_id=i.owner
           JOIN part2_versions v USING(task_id,version) WHERE u.id=$1 AND i.id=$2""",
        owner,
        issue,
    )
    if not row:
        return None
    facts = [Fact(row["issued_at"], "issued", 0)]
    for grade in await conn.fetch(
        """SELECT revision,score,status,created_at,adaptive_hint,adaptive_solution,
           result->>'needs_review' review, result->>'status' assessed_status,
           result->>'score' assessed_score,
           CASE WHEN jsonb_typeof(result->'criterion_evidence')='array'
           THEN jsonb_array_length(result->'criterion_evidence') END evidence FROM part2_grades
           WHERE issue_id=$1 AND status<>'pending' ORDER BY revision""",
        issue,
    ):
        at, score, rev = grade["created_at"], grade["score"], grade["revision"]
        if rev != 1 or row["repeat_kind"]:
            outcome = "revision"
        elif (
            grade["status"] != "graded"
            or not row["reviewed"]
            or grade["review"] != "false"
            or grade["assessed_status"] != grade["status"]
            or grade["assessed_score"] != str(score)
            or not grade["evidence"]
        ):
            outcome = "ungraded"
        else:
            outcome = "correct" if score == 2 else "wrong"
        hint, solution = grade["adaptive_hint"], grade["adaptive_solution"]
        helped = None if hint is None or solution is None else hint or solution
        facts.append(Fact(at, outcome, rev, rev, helped, score, grade["status"], hint, solution))
    if row["solution_viewed_at"]:
        facts.append(Fact(row["solution_viewed_at"], "solution", -1))
    return Item(row["number"], row["subtype_id"], row["task_id"], "written", str(issue), facts)
