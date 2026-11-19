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

from app.bot.callbacks import answer_callback
from app.bot.presentation import send_photo, send_text
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


def _keyboard(token: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not completed:
        rows.append(
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"replay:{token}:h"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"replay:{token}:s"),
            ]
        )
    rows.extend(
        (
            [InlineKeyboardButton(text="↩ К ошибкам", callback_data="progress:errors:0")],
            [InlineKeyboardButton(text="↩ В меню", callback_data="nav:main")],
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
    if parsed is None:
        return None
    return bool(policy.accepts(raw, answer))


def _original_png(source: ReplaySource) -> bytes | None:
    snapshot = source.snapshot
    family = str(snapshot.get("family_id", ""))
    if family.startswith("OGE07-N"):
        from app.math.oge07_graph import generate_graph_problem
        from app.math.oge07_validation import validate_task7_snapshot
        from app.persistence.image_retention import restore_graphic_snapshot

        restored = restore_graphic_snapshot(snapshot) or snapshot
        validate_task7_snapshot(restored)
        data = restored.get("graph_png_base64")
        if isinstance(data, str):
            return base64.b64decode(data, validate=True)
        generated = generate_graph_problem(family, int(cast(int, snapshot["seed"]))).to_snapshot()
        if generated != snapshot:
            raise ValueError("The original graph could not be verified")
        return base64.b64decode(str(generated["graph_png_base64"]), validate=True)
    if family.startswith("OGE11-"):
        from app.math.oge11 import from_snapshot as restore_oge11

        return restore_oge11(snapshot).png_bytes
    if family.startswith("OGE13-"):
        from app.math.inequalities import render_option_sheet_snapshot_png

        return render_option_sheet_snapshot_png(snapshot)
    if family.startswith("OGE15-"):
        from app.math.oge15_triangles import from_snapshot as restore_oge15

        image = restore_oge15(snapshot).png_bytes
        return image or None
    if family.startswith("OGE16-"):
        from app.math.oge16_circles import from_snapshot as restore_oge16

        return restore_oge16(snapshot).png
    if family.startswith("OGE17-"):
        from app.math.oge17_generator import from_snapshot as restore_oge17

        problem_id = str(snapshot.get("problem_id", ""))
        restored = restore_oge17(snapshot, expected_problem_id=problem_id).to_snapshot()
        return base64.b64decode(str(restored["png_base64"]), validate=True)
    if family.startswith("OGE18-"):
        from app.math.oge18 import from_snapshot as restore_oge18

        return restore_oge18(snapshot).png_bytes
    for key in ("graph_png_base64", "png_base64", "image_base64", "picture_base64"):
        payload = snapshot.get(key)
        if isinstance(payload, str):
            return base64.b64decode(payload, validate=True)
    return None


async def _render(
    message: Message, repository: Repository, store: ErrorReplayRepository,
    replay: dict[str, object], source: ReplaySource, *, user_id: int | None = None,
    status_text: str | None = None, prepared_photo: bytes | None = None,
    photo_prepared: bool = False,
) -> None:
    user_id = user_id or _user_id(message)
    replay_id = UUID(str(replay["id"]))
    token = replay_token(replay_id)
    completed = replay.get("status") != "active"
    body = f"Повтор исходной задачи №{source.number}\n\n{source.condition}"
    if status_text:
        body += "\n\n" + status_text
    if completed:
        body += "\n\n" + (
            "✅ Ошибка исправлена."
            if replay.get("status") == "solved"
            else "Повтор использован. Первоначальный результат сохранён."
        )
    else:
        attempt_count = int(cast(int, replay.get("attempt_count", 0)))
        body += f"\n\nПопытка {attempt_count + 1} из 2. Ответ не изменит исходную статистику."
    markup = _keyboard(token, completed=completed)
    photo = prepared_photo if photo_prepared else await asyncio.to_thread(
        _render_snapshot_photo, source
    )
    if photo is not None:
        sent = await send_photo(
            message, repository, BufferedInputFile(photo, filename="original-task.png"),
            caption=body, reply_markup=markup, user_id_override=user_id,
        )
    else:
        sent = await send_text(
            message, repository, body, reply_markup=markup, user_id_override=user_id,
        )
    if not completed and type(sent.message_id) is int:
        await store.set_prompt(user_id, replay_id, sent.message_id)


def _user_id(message: Message) -> int:
    sender = message.from_user
    if sender is None:
        raise ValueError("Telegram user identity is missing")
    return sender.id


def _render_snapshot_photo(source: ReplaySource) -> bytes | None:
    if source.scenario_snapshot is not None:
        from app.math.scenario_engine import ScenarioSnapshot
        from app.math.scenarios.mobile_photos import scenario_photos_for_question

        snapshot = ScenarioSnapshot.from_snapshot(source.scenario_snapshot)
        photos = scenario_photos_for_question(snapshot, source.number)
        return photos[0] if photos else None
    return _original_png(source)


async def start_from_progress(
    message: Message, repository: Repository, user_id: int, record_id: str,
) -> None:
    store = ErrorReplayRepository(repository)
    try:
        source = await load_replay_source(repository, user_id, record_id)
        photo = await asyncio.to_thread(_render_snapshot_photo, source)
        replay = await store.start(user_id, source)
    except ReplayAlreadyActive:
        await send_text(
            message,
            repository,
            "Сначала завершите текущий повтор или вернитесь к нему из подробностей ошибки.",
            user_id_override=user_id,
        )
        return
    except (ValueError, KeyError, TypeError, binascii.Error, RuntimeError):
        await send_text(
            message, repository,
            "Исходное задание недоступно для точного восстановления. "
            "Просмотр исходного условия остаётся доступен.",
            user_id_override=user_id,
        )
        return
    if replay["status"] == "active":
        await _render(
            message, repository, store, replay, source,
            user_id=user_id, prepared_photo=photo, photo_prepared=True,
        )
    else:
        await _render(
            message, repository, store, replay, source,
            user_id=user_id, prepared_photo=photo, photo_prepared=True,
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
        await send_text(message, repository, "Откройте повтор из раздела «Мои ошибки».")
        return
    replay, source = active
    from app.bot.training_ux import matches_current_condition

    if not matches_current_condition(
        message, {"problem_prompt_message_id": replay.get("prompt_message_id")}
    ):
        return
    correct = _accepts(source, message.text)
    if correct is None:
        await send_text(message, repository, "Введите ответ в формате, указанном в условии.")
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
        text = "Пока неверно. Попробуйте ещё раз."
    elif result.get("status") == "solved":
        text = "✅ Верно! Ошибка исправлена в учебном повторе."
    else:
        text = "Правильный ответ: " + source.correct_answer
    await _render(message, repository, store, result, source, status_text=text)


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
    if parts[2] == "b":
        await repository.save_user_state(callback.from_user.id, "progress")
        await answer_callback(callback)
        return
    active = await _active_replay(repository, callback.from_user.id, replay_id)
    if active is None:
        await answer_callback(callback, "Этот повтор недоступен.")
        return
    replay, source = active
    if parts[2] == "h":
        text = await store.action(callback.from_user.id, replay_id, "hint", source.snapshot)
        if text is None:
            await answer_callback(callback, "Подсказка недоступна.")
            return
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            replay["hints_used"] = int(cast(int, replay.get("hints_used", 0))) + 1
            await _render(
                callback.message,
                repository,
                store,
                replay,
                source,
                user_id=callback.from_user.id,
                status_text="Подсказка:\n" + text,
            )
        return
    if parts[2] == "s":
        solution = await store.action(callback.from_user.id, replay_id, "solution", source.snapshot)
        if solution is None:
            await answer_callback(callback, "Разбор уже открыт или повтор завершён.")
            return
        replay["status"] = "solution_viewed"
        replay["solution_viewed"] = True
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            await _render(
                callback.message,
                repository,
                store,
                replay,
                source,
                user_id=callback.from_user.id,
                status_text=(
                    "Разбор открыт. Самостоятельный зачёт за повтор закрыт.\n" + solution
                ),
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
