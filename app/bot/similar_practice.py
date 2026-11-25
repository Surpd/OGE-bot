"""Open a new ordinary practice task of the same public family as a saved mistake."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from typing import cast

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.mixed_training import _builders
from app.bot.presentation import send_text
from app.bot.training_engine import recover_saved_training
from app.bot.trainings import BY_NUMBER
from app.math.scenario_engine import (
    PracticeMode,
    PracticePlan,
    PracticeRequest,
    ScenarioSnapshot,
    ScenarioUnavailable,
)
from app.math.scenarios.recent_questions import (
    NoFreshScenarioVariant,
    ScenarioVariantSearchFailed,
    fresh_family_plan,
    question_signature,
)
from app.persistence.error_replay import ReplaySource, load_replay_source
from app.persistence.repository import Repository
from app.persistence.rotation_history import enabled
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
    return isinstance(family, str) and family in enabled(source.number)


def _candidates(source: ReplaySource, state: dict[str, object]) -> list[dict[str, object]]:
    fingerprint = source.snapshot["fingerprint"]
    recent = state.get("recent_fingerprints")
    return targeted_candidates(source.number, str(source.snapshot["family_id"]), {
        **state,
        "recent_fingerprints": [*(recent if isinstance(recent, list) else []), fingerprint],
    })


def targeted_candidates(
    number: int, family: str, state: dict[str, object],
) -> list[dict[str, object]]:
    selection = {**state, "family_queue": [family], "selected_family_id": family}
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
        if candidate.get("family_id") == family and candidate.get("fingerprint") not in cast(
            list[str], selection.get("recent_fingerprints", [])
        )
    ]


def _scenario_plan(
    source: ReplaySource, recent: frozenset[tuple[str, str, str]], seen: list[str],
) -> PracticePlan | None:
    from app.bot.scenario_training import public_registry

    if source.scenario_snapshot is None:
        return None
    original = ScenarioSnapshot.from_snapshot(source.scenario_snapshot)
    position = source.number
    question = original.questions[position - 1]
    excluded = recent | {question_signature(original, question)}
    try:
        return fresh_family_plan(
            PracticeRequest(
                PracticeMode.SINGLE, secrets.randbelow(2**63), original.story_code, position,
                family_id=question.family_id,
            ),
            public_registry(), excluded, recent_fingerprints=seen,
        )
    except NoFreshScenarioVariant:
        return None


def _choices(token: str, *, active: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if active:
        rows.append([InlineKeyboardButton(
            text="Начать похожее", callback_data=f"progress:similar:{token}:y",
        )])
    rows.append([InlineKeyboardButton(text="↩ К ошибкам", callback_data="progress:errors:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _origin(
    repository: Repository, learner: int, source: ReplaySource, kind: str, task: str,
) -> None:
    from app.config import get_settings

    pool = getattr(repository, "_pool", None)
    if pool is not None and get_settings().oge_adaptive_enabled:
        original = str(source.source_id)
        if source.source_type == "scenario":
            original += f":{source.source_position}"
        await pool.execute("""INSERT INTO adaptive_origins
            SELECT id,$2,$3,$4,$5 FROM users WHERE telegram_user_id=$1 ON CONFLICT DO NOTHING""",
            learner, kind, task, source.source_type, original)


async def _start_scenario(
    message: Message, repository: Repository, user_id: int, source: ReplaySource,
    token: str, *, confirmed: bool,
) -> bool:
    from app.adaptive.session import Session
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
    owner = await pool.fetchval("SELECT id FROM users WHERE telegram_user_id=$1", user_id)
    family = str(source.snapshot["family_id"])
    seen = await Session(repository, user_id).seen(owner, family)
    plan = await asyncio.to_thread(
        _scenario_plan, source, await store.recent_questions(user_id), seen,
    )
    if plan is None:
        return False
    session = await store.start_session(
        user_id, plan.snapshot, plan.mode, plan.selected_positions,
        replace_session_id=active.session_id if active is not None else None,
        expected_screen="progress",
    )
    if session is None:
        return False
    await _origin(repository, user_id, source, "scenario", f"{session.session_id}:{source.number}")
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
    current = await recover_saved_training(repository, user_id, mode)
    saved_state = current.get("state") if current else None
    state = cast(dict[str, object], saved_state) if isinstance(saved_state, dict) else {}
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
    candidates = await asyncio.to_thread(_candidates, source, state)
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
    await _origin(repository, user_id, source, "ordinary", str(issued["problem_id"]))
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
    except ScenarioVariantSearchFailed:
        if await repository.user_state(user_id) == "progress":
            await send_text(
                message, repository, "Не получилось подготовить похожую задачу. Попробуй ещё раз.",
                reply_markup=_choices(token), user_id_override=user_id,
            )
        return
    except (ValueError, KeyError, TypeError, ScenarioUnavailable):
        pass
    if await repository.user_state(user_id) == "progress":
        await send_text(
            message, repository, "Сейчас нет новой похожей задачи этого типа.",
            reply_markup=_choices(token), user_id_override=user_id,
        )
