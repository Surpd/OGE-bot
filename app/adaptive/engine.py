"""Deterministic evidence projection. Times are UTC Unix seconds, including fractions."""

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path


class Stage(StrEnum):
    UNCHECKED = "unchecked"
    CHECK = "check"
    GAP = "gap"
    PRACTICE = "practice"
    CONFIRMED = "confirmed"
    REOPENED = "reopened"


@dataclass(frozen=True)
class Policy:
    version: int
    practice_count: int
    diagnostic_days: int
    distinct_errors: int
    attempts_per_task: int


CURRENT = Policy(**json.loads(Path(__file__).with_name("policy_v2.json").read_text()))


@dataclass(frozen=True)
class Evidence:
    task: str
    variant: str
    time: float
    outcome: str
    attempt: int
    assisted: bool | None
    fresh: bool
    issued: float | None = None


@dataclass(frozen=True)
class State:
    stage: str = Stage.UNCHECKED
    practice: int = 0
    opened: int = 0
    closed: int = 0
    # Limited to the current diagnostic window, cleared after a full independent streak.
    errors: tuple[tuple[str, str, float], ...] = ()


def apply_written(state: State, event: Evidence) -> tuple[State, str | None]:
    """A reliable grade can suggest a subtype. Written work has no mastery cycle."""
    if event.outcome == "wrong":
        return State(stage=Stage.CHECK), "written_recommended"
    if event.outcome == "correct" and event.assisted is False and event.fresh:
        return State(), "written_independent"
    return state, None


def apply(state: State, event: Evidence, policy: Policy = CURRENT) -> tuple[State, str | None]:
    if event.outcome in {"issued", "skip", "invalid", "revision", "replay", "ungraded"}:
        return state, None
    active = state.opened > state.closed
    gap_stage = Stage.REOPENED if state.closed else Stage.GAP
    if event.outcome == "ambiguous":
        return replace(state, stage=Stage.CHECK, practice=0), "thematic_check_needed"
    if event.outcome == "wrong":
        errors = tuple(
            e for e in state.errors if e[2] >= event.time - policy.diagnostic_days * 86400
        )
        errors += ((event.task, event.variant, event.time),)
        repeated = sum(t == event.task for t, _, _ in errors) >= policy.attempts_per_task
        enough = repeated or len({v for _, v, _ in errors if v}) >= policy.distinct_errors
        if enough or active:
            reason = (
                "practice_again" if active else "gap_reopened" if state.closed else "gap_opened"
            )
            return replace(
                state, stage=gap_stage, opened=state.opened + int(not active), practice=0, errors=()
            ), reason
        return replace(state, stage=Stage.CHECK, practice=0, errors=errors), "diagnostic_signal"
    if event.outcome != "correct" or event.attempt != 1 or event.assisted is not False:
        return replace(
            state, stage=gap_stage if active else Stage.CHECK, practice=0
        ), "independent_check_needed"
    if not event.fresh or not event.variant or state.stage == Stage.CONFIRMED:
        return state, None
    streak = state.practice + 1
    if streak >= policy.practice_count:
        return replace(
            state, stage=Stage.CONFIRMED, practice=streak, errors=(), closed=state.opened
        ), "gap_closed" if active else "skill_confirmed"
    return replace(state, stage=Stage.PRACTICE, practice=streak), "independent_success"
