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
class FamilyStatus:
    key: str
    label: str
    practice: int
    target: int


@dataclass(frozen=True)
class Policy:
    version: int
    practice_count: int
    diagnostic_days: int
    distinct_errors: int
    attempts_per_task: int
    review_days: int


CURRENT = Policy(**json.loads(Path(__file__).with_name("policy_v3.json").read_text()))


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
    last_independent: float | None = None
    confirmed_at: float | None = None
    reviewed_at: float | None = None
    independent_count: int = 0


_STATUS_LABELS = {
    Stage.UNCHECKED: "Нет данных",
    Stage.CHECK: "Нужно проверить",
    Stage.GAP: "Нужно потренировать",
    Stage.PRACTICE: "Закрепляется",
    Stage.CONFIRMED: "Получается",
    Stage.REOPENED: "Нужно потренировать",
}


def family_status(state: State, policy: Policy = CURRENT) -> FamilyStatus:
    """Return deliberately modest, student-facing wording for a family projection."""
    stage = Stage(state.stage)
    return FamilyStatus(
        key=stage.value,
        label=_STATUS_LABELS[stage],
        practice=min(state.practice, policy.practice_count),
        target=policy.practice_count,
    )


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
    # A repeated mathematical condition and legacy rows without a stable
    # content fingerprint are useful for practice, but never independent
    # diagnostic evidence. This guard applies to wrong/ambiguous/helped events
    # as well as successes, so they cannot open or interrupt a streak.
    if not event.fresh or not event.variant:
        return state, None
    active = state.opened > state.closed
    gap_stage = Stage.REOPENED if state.closed else Stage.GAP
    if event.outcome == "ambiguous":
        return replace(state, stage=Stage.CHECK, practice=0), "thematic_check_needed"
    if event.outcome == "wrong":
        errors = tuple(
            e for e in state.errors if e[2] >= event.time - policy.diagnostic_days * 86400
        )
        # Several inputs against one unchanged condition are one mathematical
        # observation. Keep its latest timestamp, but never promote it to an
        # independent second error.
        errors = tuple(e for e in errors if e[0] != event.task)
        errors += ((event.task, event.variant, event.time),)
        enough = len({v for _, v, _ in errors if v}) >= policy.distinct_errors
        if enough or active:
            reason = (
                "practice_again" if active else "gap_reopened" if state.closed else "gap_opened"
            )
            return replace(
                state, stage=gap_stage, opened=state.opened + int(not active), practice=0, errors=()
            ), reason
        return replace(state, stage=Stage.CHECK, practice=0, errors=errors), "diagnostic_signal"
    if event.outcome != "correct" or event.attempt != 1 or event.assisted is True:
        return replace(
            state, stage=gap_stage if active else Stage.CHECK, practice=0
        ), "independent_check_needed"
    if event.assisted is None:
        return state, None
    if state.stage == Stage.CONFIRMED:
        delayed = (
            state.last_independent is not None
            and event.time - state.last_independent >= policy.review_days * 86400
        )
        return replace(
            state,
            last_independent=event.time,
            reviewed_at=event.time if delayed else state.reviewed_at,
            independent_count=state.independent_count + 1,
        ), "independent_review" if delayed else None
    streak = state.practice + 1
    if streak >= policy.practice_count:
        return replace(
            state,
            stage=Stage.CONFIRMED,
            practice=streak,
            errors=(),
            closed=state.opened,
            last_independent=event.time,
            confirmed_at=event.time,
            independent_count=state.independent_count + 1,
        ), "gap_closed" if active else "skill_confirmed"
    return replace(
        state,
        stage=Stage.PRACTICE,
        practice=streak,
        last_independent=event.time,
        independent_count=state.independent_count + 1,
    ), "independent_success"
