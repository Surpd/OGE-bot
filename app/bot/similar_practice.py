"""Open a new ordinary practice task of the same public family as a saved mistake."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from importlib import import_module
from typing import cast

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.mixed_training import _builders
from app.bot.presentation import send_text
from app.bot.trainings import BY_NUMBER
from app.math.scenario_engine import (
    PracticeMode,
    PracticePlan,
    PracticeRequest,
    ScenarioSnapshot,
    ScenarioUnavailable,
    build_practice_plan,
)
from app.math.scenarios.recent_questions import is_recent_fixed_single, question_signature
from app.persistence.error_replay import ReplaySource, load_replay_source
from app.persistence.repository import Repository
from app.persistence.scenario_repository import ScenarioPostgresRepository


def supports_similar(source: ReplaySource) -> bool:
    family = source.snapshot.get("family_id")
    if source.scenario_snapshot is not None:
        from app.bot.scenario_training import public_registry

        story = str(source.scenario_snapshot["story_code"])
        registry = public_registry()
        return story in registry.available_stories(PracticeMode.SINGLE, source.number) and any(
            registered.available and registered.family_id == family
            and registered.position == source.number
            for registered in registry.adapter(story).family_registry
        )
    training = BY_NUMBER.get(source.number)
    if training is None or not training.available:
        return False
    if source.number == 6:
        from app.math.registry import SPEC_BY_ID

        return isinstance(family, str) and family in SPEC_BY_ID
    module = import_module(_builders()[source.number].__module__)
    return family in getattr(module, "ENABLED_FAMILIES", ())


def _candidates(source: ReplaySource, state: dict[str, object]) -> list[dict[str, object]]:
    number = source.number
    family = str(source.snapshot["family_id"])
    fingerprint = source.snapshot["fingerprint"]
    recent = state.get("recent_fingerprints")
    selection = {
        **state,
        "family_queue": [family],
        "recent_fingerprints": [*(recent if isinstance(recent, list) else []), fingerprint],
    }
    builder = cast(Callable[..., list[dict[str, object]]], _builders()[number])
    seed = secrets.randbelow(2**63)
    if number == 7:
        batch = builder(selection, seed, family_ids=(family,), limit=1)
    elif number in {11, 15, 16, 17, 18, 19}:
        batch = builder(selection, seed, enabled_families=(family,))
    else:
        batch = builder(selection, seed)
    return [
        candidate for candidate in batch
        if candidate.get("family_id") == family and candidate.get("fingerprint") != fingerprint
    ]


def _scenario_plan(
    source: ReplaySource, recent: frozenset[tuple[str, str, str]]
) -> PracticePlan | None:
    from app.bot.scenario_training import public_registry

    if source.scenario_snapshot is None:
        return None
    original = ScenarioSnapshot.from_snapshot(source.scenario_snapshot)
    position = source.number
    question = original.questions[position - 1]
    excluded = recent | {question_signature(original, question)}
    if is_recent_fixed_single(PracticePlan(PracticeMode.SINGLE, original, (position,)), excluded):
        return None
    registry = public_registry()
    for _ in range(12):
        plan = build_practice_plan(
            PracticeRequest(
                PracticeMode.SINGLE, secrets.randbelow(2**63), original.story_code, position,
            ),
            registry,
        )
        candidate = plan.snapshot.questions[position - 1]
        if candidate.family_id == question.family_id and question_signature(
            plan.snapshot, candidate,
        ) not in excluded:
            return plan
    return None


def _choices(token: str, *, active: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if active:
        rows.append([InlineKeyboardButton(
            text="Начать похожее", callback_data=f"progress:similar:{token}:y",
        )])
    rows.append([InlineKeyboardButton(text="↩ К ошибкам", callback_data="progress:errors:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _start_scenario(
    message: Message, repository: Repository, user_id: int, source: ReplaySource,
    token: str, *, confirmed: bool,
) -> bool:
    from app.bot.scenario_training import render_session

    pool = getattr(repository, "_pool", None)
    if pool is None or source.scenario_snapshot is None:
        return False
    store = ScenarioPostgresRepository(pool)
    story = str(source.scenario_snapshot["story_code"])
    active = await store.find_open_session(user_id, story, PracticeMode.SINGLE)
    if active is not None and active.question_status == "active" and not confirmed:
        await send_text(
            message, repository,
            "У вас есть незавершённое задание в этом сюжете. "
            "Если начать похожее, текущий вопрос останется в истории без завершения.",
            reply_markup=_choices(token, active=True), user_id_override=user_id,
        )
        return True
    plan = await asyncio.to_thread(_scenario_plan, source, await store.recent_questions(user_id))
    if plan is None:
        return False
    session = await store.start_session(
        user_id, plan.snapshot, plan.mode, plan.selected_positions,
        replace_session_id=active.session_id if active is not None else None,
        expected_screen="progress",
    )
    if session is None:
        return False
    await render_session(
        message, store, session, show_assets=True, user_id_override=user_id,
        repository=repository,
    )
    return True


async def _start_ordinary(
    message: Message, repository: Repository, user_id: int, source: ReplaySource,
    token: str, *, confirmed: bool,
) -> bool:
    from app.bot import router

    number = source.number
    mode = BY_NUMBER[number].mode
    await getattr(repository, f"ensure_{mode}_session")(user_id)
    current = await getattr(repository, f"{mode}_state")(user_id)
    state = current.get("state", {}) if current else {}
    problem = current.get("problem") if current else None
    problem_id = str(problem["problem_id"]) if isinstance(problem, dict) else None
    active = problem_id is not None and state.get("status") == "active"
    if active and not confirmed:
        await send_text(
            message, repository,
            f"У вас есть незавершённое задание №{number}. "
            "Если начать похожее, текущее задание останется в истории без завершения.",
            reply_markup=_choices(token, active=True), user_id_override=user_id,
        )
        return True
    candidates = await asyncio.to_thread(_candidates, source, cast(dict[str, object], state))
    if not candidates:
        return False
    previous_status = None
    if active and problem_id is not None:
        previous_status = await repository.prepare_training_restart(
            user_id, mode, problem_id, "progress"
        )
        if previous_status is None:
            return False
    try:
        issued = await getattr(repository, f"advance_{mode}_problem")(
            user_id, problem_id, candidates, expected_screen="progress",
        )
    except RuntimeError:
        issued = {}
    if not issued or issued.get("_transitioned") is False:
        if previous_status is not None and problem_id is not None:
            await repository.restore_training_restart(user_id, mode, problem_id, previous_status)
        return False
    sender = router._send_problem if number == 6 else getattr(router, f"_send_{mode}_problem")
    return bool(await sender(
        message, repository, action="resume", expected_problem_id=str(issued["problem_id"]),
        expected_screen="progress", user_id_override=user_id,
    ))


async def start_similar(
    message: Message, repository: Repository, user_id: int, token: str, *, confirmed: bool,
) -> None:
    from app.bot.progress import decode_record_ref

    try:
        source = await load_replay_source(repository, user_id, decode_record_ref(token))
        if supports_similar(source):
            starter = _start_scenario if source.scenario_snapshot is not None else _start_ordinary
            if await starter(message, repository, user_id, source, token, confirmed=confirmed):
                return
    except (ValueError, KeyError, TypeError, ScenarioUnavailable):
        pass
    if await repository.user_state(user_id) == "progress":
        await send_text(
            message, repository, "Сейчас нет новой похожей задачи этого типа.",
            reply_markup=_choices(token), user_id_override=user_id,
        )
