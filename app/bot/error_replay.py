"""Telegram flow for one-time, reference-only repetition of an original mistake."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from typing import Any, cast
from uuid import UUID

from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.bop_copy import LABELS, reply
from app.bot.callbacks import answer_callback
from app.bot.math_layout import question_message, solution_message
from app.bot.presentation import hint_message, send_photo, send_text
from app.bot.scenario_materials import prepare_scenario_materials, send_scenario_materials
from app.bot.task_view import answer_instruction, question_text, system_rows, verified_photo
from app.math.scenario_engine import ScenarioSnapshot
from app.persistence.error_replay import (
    ErrorReplayRepository,
    ReplayAlreadyActive,
    ReplaySource,
    load_replay_source,
)
from app.persistence.repository import Repository


def replay_token(value: UUID) -> str:
    return base64.b32encode(value.bytes).decode("ascii").rstrip("=").lower()


def replay_uuid(token: str) -> UUID:
    if not re.fullmatch(r"[a-z2-7]{26}", token):
        raise ValueError("Invalid replay ID")
    return UUID(bytes=base64.b32decode(token.upper() + "=" * ((8 - len(token) % 8) % 8)))


def _keyboard(
    token: str, *, completed: bool = False, scenario: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not completed:
        rows.append(
            [
                InlineKeyboardButton(text=LABELS["hint"], callback_data=f"replay:{token}:h"),
                InlineKeyboardButton(text=LABELS["solution"], callback_data=f"replay:{token}:s"),
            ]
        )
    if scenario and not completed:
        rows.append([InlineKeyboardButton(
            text=LABELS["data"], callback_data=f"replay:{token}:d",
        )])
    rows.extend(
        (
            [InlineKeyboardButton(text="↩ К ошибкам", callback_data="progress:errors:0")],
            [InlineKeyboardButton(text=LABELS["menu"], callback_data="nav:main")],
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _policy_for(source: ReplaySource) -> Any:
    snapshot = source.snapshot
    number = source.number
    policy_id = str(snapshot.get("answer_policy_id", ""))
    policy_version = str(snapshot.get("answer_policy_version", ""))
    policy: Any = None
    if number in range(1, 6):
        from app.bot.scenario_training import public_registry

        story = str(snapshot.get("story_code", ""))
        policy = public_registry().adapter(story).answer_policies.get((policy_id, policy_version))
        if policy is None:
            raise ValueError("The original answer policy is unavailable")
        return policy
    if number == 6:
        from app.math.registry import ANSWER_POLICY_BY_SNAPSHOT

        policy = ANSWER_POLICY_BY_SNAPSHOT.get((str(snapshot.get("family_id", "")),
                                               policy_id, policy_version))
    elif number == 7:
        from app.math.numbers import POLICY

        policy = (
            POLICY
            if (policy_id, policy_version) == (POLICY.policy_id, POLICY.version)
            else None
        )
    elif number == 9:
        from app.math.equations import ANSWER_POLICIES_BY_SNAPSHOT

        policy = ANSWER_POLICIES_BY_SNAPSHOT.get((policy_id, policy_version))
    elif number == 11:
        from app.math.oge11 import POLICY_ID, POLICY_VERSION

        policy = ("oge11" if (policy_id, policy_version) == (POLICY_ID, POLICY_VERSION) else None)
    elif number == 19:
        from app.math.oge19 import policy_for_snapshot

        policy = policy_for_snapshot(snapshot)
    elif number == 13:
        from app.math.inequalities import POLICY

        policy = (
            POLICY
            if (policy_id, policy_version) == (POLICY.policy_id, POLICY.version)
            else None
        )
    else:
        from app.bot.training_engine import NUMERIC_TRAININGS

        training = NUMERIC_TRAININGS.get(number)
        policy = training.policy if training and (policy_id, policy_version) == (
            training.policy.policy_id, training.policy.version
        ) else None
    if policy is None:
        raise ValueError("The original answer policy is unavailable")
    return policy


def _accepts(source: ReplaySource, raw: str) -> bool | None:
    snapshot = source.snapshot
    answer = source.correct_answer
    policy = _policy_for(source)
    if source.number == 13:
        choice = raw.strip()
        return choice == answer if choice in {"1", "2", "3", "4"} else None
    if source.number == 11:
        from app.math.oge11 import parse_answer

        parsed = parse_answer(raw)
        return None if parsed is None else parsed == answer
    if source.number in range(1, 6):
        from app.bot.scenario_training import _valid_answer_format

        if not _valid_answer_format(str(snapshot.get("story_code", "")),
                                    str(snapshot.get("answer_policy_id", "")), raw):
            return None
        return bool(policy.accepts(raw, answer))
    parsed = policy.parse(raw)
    if parsed is None or (source.number == 7 and parsed not in range(1, 5)):
        return None
    return bool(policy.accepts(raw, answer))


def _condition(source: ReplaySource) -> str:
    return (
        question_text(source.number, source.snapshot) + "\n\n"
        + answer_instruction(source.number, source.snapshot)
    )


async def _render(
    message: Message, repository: Repository, store: ErrorReplayRepository,
    replay: dict[str, object], source: ReplaySource, *, user_id: int,
    materials: tuple[str, tuple[bytes, ...]], notice: str = "",
    controls: InlineKeyboardMarkup | None = None,
) -> None:
    token = replay_token(UUID(str(replay["id"])))
    completed = replay.get("status") != "active"
    if completed:
        await repository.save_user_state(user_id, "progress")
        await send_text(
            message, repository, "Этот повтор уже завершён.",
            reply_markup=_keyboard(token, completed=True), user_id_override=user_id,
        )
        return
    attempt_count = int(cast(int, replay.get("attempt_count", 0)))
    body = question_message(
        f"Повтор исходной задачи №{source.number}",
        _condition(source),
        f"Попытка {attempt_count + 1} из 2. Повтор учитывается отдельно.",
        position=notice,
    )
    context, photos = materials
    if source.scenario_snapshot is not None:
        if not await send_scenario_materials(
            message, repository, ScenarioSnapshot.from_snapshot(source.scenario_snapshot),
            source.number, user_id=user_id,
        ):
            return
    elif context:
        await send_text(
            message, repository, context, user_id_override=user_id, math_family=source.snapshot
        )
        for data in photos:
            await send_photo(
                message, repository, BufferedInputFile(data, filename="scenario.png"),
                caption=f"Данные задачи №{source.number}", user_id_override=user_id,
            )
    photo = photos[0] if photos and not context else None
    math_system_rows = system_rows(source.number, source.snapshot)
    markup = controls if controls is not None else _keyboard(
        token, completed=completed, scenario=source.scenario_snapshot is not None
    )
    if photo is not None:
        sent = await send_photo(
            message, repository, BufferedInputFile(photo, filename="original-task.png"),
            caption=body, reply_markup=markup, user_id_override=user_id,
            math_system_rows=math_system_rows,
            diagram_caption=(
                f"Данные задачи №{source.number}" if source.number in {11, 13} else None
            ),
            math_family=source.snapshot,
        )
    else:
        sent = await send_text(
            message, repository, body, reply_markup=markup, user_id_override=user_id,
            rich_with_navigation=True, math_system_rows=math_system_rows,
            math_family=source.snapshot,
        )
    await store.set_prompt(user_id, UUID(str(replay["id"])), sent.message_id)


def _materials(source: ReplaySource) -> tuple[str, tuple[bytes, ...]]:
    if source.scenario_snapshot is not None:
        snapshot = ScenarioSnapshot.from_snapshot(source.scenario_snapshot)
        return prepare_scenario_materials(snapshot, source.number)
    photo = verified_photo(source.number, source.snapshot)
    return "", (photo,) if photo is not None else ()


async def start_from_progress(
    message: Message, repository: Repository, user_id: int, record_id: str,
) -> None:
    store = ErrorReplayRepository(repository)
    notice = ""
    try:
        source = await load_replay_source(repository, user_id, record_id)
        _policy_for(source)
        materials = await asyncio.to_thread(_materials, source)
        _condition(source)
        try:
            replay = await store.start(user_id, source)
        except ReplayAlreadyActive:
            active = await _active_replay(repository, user_id)
            if active is None:
                raise ValueError("The active replay cannot be restored") from None
            replay, source = active
            _policy_for(source)
            materials = await asyncio.to_thread(_materials, source)
            _condition(source)
            await store.set_screen(user_id, "error_replay")
            notice = "Продолжаем незавершённый повтор."
    except (ValueError, KeyError, TypeError, binascii.Error, RuntimeError):
        await send_text(
            message, repository, "Не удалось восстановить исходную задачу для повтора. "
            "Открой задачу ещё раз из списка ошибок.",
            reply_markup=_keyboard("", completed=True), user_id_override=user_id,
        )
        return
    await _render(
        message, repository, store, replay, source,
        user_id=user_id, materials=materials, notice=notice,
    )


async def _feedback(
    message: Message, repository: Repository, user_id: int,
    replay: dict[str, object], text: str, math_family: object = None, *, scenario: bool = False,
) -> None:
    # Send feedback separately. Replies to the original condition stay valid.
    await send_text(
        message, repository, text,
        reply_markup=_keyboard(
            replay_token(UUID(str(replay["id"]))), completed=replay["status"] != "active",
            scenario=scenario,
        ),
        user_id_override=user_id, rich_with_navigation=True, math_family=math_family,
    )


async def answer(message: Message, repository: Repository) -> None:
    if message.from_user is None or message.text is None:
        return
    user_id = message.from_user.id
    if await repository.user_state(user_id) != "error_replay":
        from aiogram.dispatcher.event.bases import SkipHandler

        raise SkipHandler
    store = ErrorReplayRepository(repository)
    active = await _active_replay(repository, user_id)
    if active is None:
        await send_text(message, repository, "Открой повтор из раздела «Мои ошибки».")
        return
    replay, source = active
    from app.bot.training_ux import matches_current_condition

    if not matches_current_condition(
        message, {"problem_prompt_message_id": replay.get("prompt_message_id")}
    ):
        return
    try:
        correct = _accepts(source, message.text)
    except ValueError:
        await send_text(message, repository, "Не удалось проверить ответ к исходной задаче.")
        return
    if correct is None:
        await send_text(message, repository, "Введи ответ в формате из условия.")
        return
    result = await store.record_attempt(
        user_id,
        UUID(str(replay["id"])),
        message.text,
        correct,
        message.message_id,
        message.reply_to_message.message_id if message.reply_to_message else None,
    )
    if result is None or result.get("event") in {"stale", "duplicate", "closed"}:
        return
    if result.get("status") == "active":
        text = reply("wrong", message.message_id)
    elif result.get("status") == "solved":
        text = "✅ Верно! Ошибка исправлена в учебном повторе."
    else:
        solution = source.snapshot.get("solution_steps", source.snapshot.get("solution"))
        text = solution_message(
            list(map(str, solution)) if isinstance(solution, list) else (),
            source.correct_answer, reply("review", message.message_id),
        )
    await _feedback(
        message, repository, user_id, result, text,
        source.snapshot if result.get("status") == "failed" else None,
        scenario=source.scenario_snapshot is not None,
    )


async def callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").partition("~")[0].split(":")
    if len(parts) != 3 or parts[0] != "replay":
        await answer_callback(callback, "Кнопка повтора недоступна.")
        return
    try:
        replay_id = replay_uuid(parts[1])
    except (ValueError, binascii.Error):
        await answer_callback(callback, "Кнопка повтора устарела.")
        return
    store = ErrorReplayRepository(repository)
    active = await _active_replay(repository, callback.from_user.id, replay_id)
    if active is None:
        await answer_callback(callback, "Этот повтор недоступен.")
        if isinstance(callback.message, Message):
            await repository.save_user_state(callback.from_user.id, "progress")
            await send_text(
                callback.message, repository, "Не удалось открыть исходную задачу.",
                reply_markup=_keyboard("", completed=True), user_id_override=callback.from_user.id,
            )
        return
    replay, source = active
    if parts[2] == "d" and source.scenario_snapshot is not None:
        # The navigation router claims the current message/revision first.
        # Loading by owner + replay_id alone also finds completed/paused replays.
        if (replay.get("status") != "active"
                or await repository.user_state(callback.from_user.id) != "error_replay"):
            await answer_callback(callback, "Этот повтор завершён или уже закрыт на экране.")
            return
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            await send_scenario_materials(
                callback.message, repository,
                ScenarioSnapshot.from_snapshot(source.scenario_snapshot), source.number,
                user_id=callback.from_user.id,
                reply_markup=_keyboard(parts[1], scenario=True),
            )
        return
    if parts[2] == "h":
        text = await store.action(callback.from_user.id, replay_id, "hint", source.snapshot)
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            await _feedback(
                callback.message, repository, callback.from_user.id, replay,
                hint_message(text, source.snapshot) if text is not None
                else "Подсказок больше нет.",
                source.snapshot if text is not None else None,
                scenario=source.scenario_snapshot is not None,
            )
        return
    if parts[2] == "s":
        solution = await store.action(callback.from_user.id, replay_id, "solution", source.snapshot)
        if solution is None:
            await answer_callback(callback, "Разбор уже открыт или повтор завершён.")
            return
        replay["status"] = "solution_viewed"
        await repository.save_user_state(callback.from_user.id, "progress")
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            await _feedback(
                callback.message, repository, callback.from_user.id, replay,
                solution_message(solution.splitlines(), source.correct_answer), source.snapshot,
                scenario=source.scenario_snapshot is not None,
            )
        return
    await answer_callback(callback, "Действие повтора недоступно.")


async def _active_replay(
    repository: Repository, user_id: int, replay_id: UUID | None = None,
) -> tuple[dict[str, object], ReplaySource] | None:
    if replay_id is None:
        replay = await _active_row(repository, user_id)
    else:
        replay = await _replay_by_id(repository, user_id, replay_id)
    if replay is None:
        return None
    record_id = _record_id(str(replay["source_type"]), str(replay["source_id"]),
                           cast(int, replay["source_position"]))
    try:
        source = await load_replay_source(repository, user_id, record_id)
    except (ValueError, KeyError, TypeError, RuntimeError, binascii.Error):
        return None
    return replay, source


def _record_id(source_type: str, source_id: str, position: int) -> str:
    return {"ordinary": f"o:{source_id}", "mixed": f"m:{source_id}",
            "scenario": f"s:{source_id}:{position}"}[source_type]


async def _active_row(repository: Repository, user_id: int) -> dict[str, object] | None:
    store = ErrorReplayRepository(repository)
    if store._pool is None:
        rows = [
            row
            for (owner, *_), row in getattr(repository, "_training_error_replays", {}).items()
            if owner == user_id and row["status"] == "active"
        ]
        return dict(rows[-1]) if rows else None
    row = await store._pool.fetchrow(
        """SELECT r.* FROM training_error_replays r JOIN users u ON u.id=r.user_id
           WHERE u.telegram_user_id=$1 AND r.status='active'
           ORDER BY r.updated_at DESC LIMIT 1""", user_id,
    )
    if row is None:
        return None
    from app.persistence.error_replay import _replay_row

    return _replay_row(row)


async def _replay_by_id(repository: Repository, user_id: int, replay_id: UUID
                        ) -> dict[str, object] | None:
    store = ErrorReplayRepository(repository)
    if store._pool is None:
        for (owner, *_), row in getattr(repository, "_training_error_replays", {}).items():
            if owner == user_id and row["id"] == str(replay_id):
                return dict(row)
        return None
    row = await store._pool.fetchrow(
        """SELECT r.* FROM training_error_replays r JOIN users u ON u.id=r.user_id
           WHERE u.telegram_user_id=$1 AND r.id=$2""", user_id, replay_id,
    )
    if row is None:
        return None
    from app.persistence.error_replay import _replay_row

    return _replay_row(row)
