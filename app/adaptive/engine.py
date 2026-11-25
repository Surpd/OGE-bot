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
    WAIT = "wait"
    CONFIRMED = "confirmed"
    REOPENED = "reopened"


@dataclass(frozen=True)
class Policy:
    version: int = 1
    practice_count: int = 2
    intervals_days: tuple[int, ...] = (2, 5)
    diagnostic_days: int = 30
    distinct_errors: int = 2
    attempts_per_task: int = 2

    def __post_init__(self) -> None:
        if (
            min(
                self.practice_count,
                self.diagnostic_days,
                self.distinct_errors,
                self.attempts_per_task,
                *self.intervals_days,
            )
            < 1
            or not self.intervals_days
        ):
            raise ValueError("Positive evidence thresholds and intervals required")


def load_policy(version: int) -> Policy:
    raw = json.loads(Path(__file__).with_name(f"policy_v{version}.json").read_text())
    raw["intervals_days"] = tuple(raw["intervals_days"])
    policy = Policy(**raw)
    if policy.version != version:
        raise ValueError("Policy version mismatch")
    return policy


V1 = load_policy(1)


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
    checks: int = 0
    due: float | None = None
    opened: int = 0
    closed: int = 0
    # Limited to the current diagnostic window, cleared after independent success.
    errors: tuple[tuple[str, str, float], ...] = ()


def apply(state: State, event: Evidence, policy: Policy = V1) -> tuple[State, str | None]:
    if event.outcome in {"issued", "skip", "invalid", "revision", "replay", "ungraded"}:
        return state, None
    if event.outcome == "ambiguous":
        return replace(state, stage=Stage.CHECK), "thematic_check_needed"
    if event.outcome == "wrong":
        errors = tuple(
            (t, v, at)
            for t, v, at in state.errors
            if at >= event.time - policy.diagnostic_days * 86400
        )
        repeated = sum(t == event.task for t, _, _ in errors) + 1 >= policy.attempts_per_task
        errors += ((event.task, event.variant, event.time),)
        enough = repeated or len({v for _, v, _ in errors if v}) >= policy.distinct_errors
        active = state.opened > state.closed
        if enough:
            stage = Stage.REOPENED if state.closed else Stage.GAP
            return State(stage, opened=state.opened + int(not active), closed=state.closed), (
                "practice_again" if active else "gap_reopened" if state.closed else "gap_opened"
            )
        return replace(state, errors=errors, stage=Stage.CHECK if not active else state.stage), (
            "diagnostic_signal"
        )
    if event.outcome != "correct" or event.attempt != 1 or event.assisted is not False:
        if state.stage in {Stage.UNCHECKED, Stage.CONFIRMED}:
            return replace(state, stage=Stage.CHECK), "independent_check_needed"
        return state, None
    if not event.variant or not event.fresh:
        return state, None
    if state.stage == Stage.CONFIRMED or (
        state.stage == Stage.CHECK
        and state.closed == state.opened
        and state.checks == len(policy.intervals_days)
    ):
        return replace(state, stage=Stage.CONFIRMED, errors=()), None
    clean = replace(state, errors=())
    if clean.due is not None:
        if event.time < clean.due or event.issued is not None and event.issued < clean.due:
            return clean, None
        checks = clean.checks + 1
        if checks == len(policy.intervals_days):
            return replace(
                clean, checks=checks, stage=Stage.CONFIRMED, due=None, closed=clean.opened
            ), ("gap_closed" if clean.opened > clean.closed else "skill_confirmed")
        return replace(
            clean,
            checks=checks,
            stage=Stage.WAIT,
            due=event.time + policy.intervals_days[checks] * 86400,
        ), "check_passed"
    practice = clean.practice + 1
    if practice >= policy.practice_count:
        return replace(
            clean,
            stage=Stage.WAIT,
            practice=practice,
            due=event.time + policy.intervals_days[0] * 86400,
        ), "practice_complete"
    return replace(clean, stage=Stage.PRACTICE, practice=practice), "independent_success"
