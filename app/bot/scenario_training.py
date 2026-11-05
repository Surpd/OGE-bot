"""Telegram UX for public OGE 1–5 scenario sessions."""

from __future__ import annotations

import re
import secrets
from dataclasses import replace
from functools import lru_cache
from types import SimpleNamespace
from uuid import UUID

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from asyncpg import UniqueViolationError

from app.bot.callbacks import answer_callback
from app.bot.training_ux import matches_current_condition
from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    ScenarioUnavailable,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)
from app.persistence.repository import Repository
from app.persistence.scenario_repository import (
    AttemptResult,
    ScenarioPostgresRepository,
    ScenarioSession,
)

PUBLIC_LABEL = "Практические задания №1–5"
STORY_NAMES = {
    "TYRES": "Шины",
    "PAPER": "Бумага",
    "STOVE": "Печи",
    "TARIFF": "Тарифы",
    "GARDEN": "Участки",
    "FLAT": "Квартиры",
}
PUBLIC_FAMILIES = {
    "TYRES": frozenset(
        {
            "TYRES-DIAMETER",
            "TYRES-PERCENT-ROTATION",
            "TYRES-RADIUS-DELTA",
            "TYRES-SIDEWALL",
            "TYRES-TABLE-EXTREME",
        }
    ),
    "PAPER": frozenset(
        {"PAPER-F01", "PAPER-F02", "PAPER-F03", "PAPER-F04", "PAPER-F06", "PAPER-F07"}
    ),
    "STOVE": frozenset(
        {
            "STOVE-F01-CAPACITY-LIMITS",
            "STOVE-F02-ATTRIBUTE-MATCH",
            "STOVE-F03-VOLUME",
            "STOVE-F04-FLOOR-AREA",
            "STOVE-F05-WALL-AREA-NET",
            "STOVE-F06-PURCHASE-EXTRA-COSTS",
            "STOVE-F07-FIT-WOOD-DELIVERY",
            "STOVE-F08-COST-COMPARISON",
            "STOVE-F09-DIRECT-DISCOUNT",
            "STOVE-F10-REVERSE-DISCOUNT",
            "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS",
            "STOVE-F12-ARCH-RADIUS",
        }
    ),
    "TARIFF": frozenset(
        {
            "TARIFF-F01-MONTHS-MINUTES",
            "TARIFF-F04-MONTHLY-BILL",
            "TARIFF-F05-EXTREMUM",
            "TARIFF-F09-PERCENT-FEE",
            "TARIFF-F12-HOME-ISP",
        }
    ),
    "GARDEN": frozenset(
        {
            "GARDEN-01-IDENTIFY",
            "GARDEN-02-TILES-PACKS",
            "GARDEN-04-PERIMETER-POLYGON",
            "GARDEN-07-PERCENT-BUILDINGS",
            "GARDEN-09-HEAT-BREAKEVEN",
        }
    ),
    "FLAT": frozenset(
        {
            "FLAT-01-ROOM-MATCH",
            "FLAT-02-TILE-PACK",
            "FLAT-02-PARQUET-PACK",
            "FLAT-03-RECT-AREA",
            "FLAT-04-RECT-PERCENT",
            "FLAT-05-WASHER-MIN",
            "FLAT-05-INTERNET-MIN",
        }
    ),
}


@lru_cache(maxsize=1)
def public_registry() -> FamilyRegistry:
    """Create a separate explicit public allowlist without changing adapter defaults."""
    adapters = []
    discovered = discover_story_registry()
    for story_code in discovered.story_codes:
        adapter = discovered.adapter(story_code)
        allowed = PUBLIC_FAMILIES.get(adapter.story_code, frozenset())
        families = tuple(
            replace(
                family,
                enabled=(
                    family.family_id in allowed and family.status.value == "enabled_candidate"
                ),
            )
            for family in adapter.family_registry
        )
        adapters.append(
            SimpleNamespace(
                story_code=adapter.story_code,
                generator=adapter.generator,
                question_builder=adapter.question_builder,
                independent_oracle=adapter.independent_oracle,
                renderer=adapter.renderer,
                answer_policies=adapter.answer_policies,
                family_registry=families,
            )
        )
    return FamilyRegistry(adapters)


def _button(label: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=callback)


def _keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _has_user(user_id: int | None) -> bool:
    return user_id is not None and user_id > 0


def _story_keyboard() -> InlineKeyboardMarkup:
    rows = [[_button(name, f"oge15:story:{code}")] for code, name in STORY_NAMES.items()]
    rows.extend(
        (
            [_button("🎲 Случайный сюжет", "oge15:story:RANDOM")],
            [_button("📊 Статистика", "oge15:stats")],
        )
    )
    return _keyboard(rows)


async def show_public_oge15(
    message: Message,
    oge15_repository: ScenarioPostgresRepository | None = None,
    repository: Repository | None = None,
) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not _has_user(user_id):
        return
    if oge15_repository is None:
        await message.answer("Практические задания №1–5 пока недоступны.")
        return
    if repository is not None and user_id is not None:
        await repository.save_user_state(user_id, "oge15_menu")
    await message.answer(
        "Практические задания №1–5\nВыберите сюжет:",
        reply_markup=_story_keyboard(),
    )


async def _send_selection(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(text, reply_markup=keyboard)
    await answer_callback(callback)


async def _story_step(callback: CallbackQuery, code: str) -> None:
    if code != "RANDOM" and code not in STORY_NAMES:
        await answer_callback(callback, "Этот сюжет недоступен.")
        return
    title = "Случайный сюжет" if code == "RANDOM" else STORY_NAMES[code]
    await _send_selection(
        callback,
        f"Сюжет: {title}. Выберите режим:",
        _keyboard(
            [
                [_button("Одно задание", f"oge15:mode:{code}:single")],
                [_button("Вся пятёрка", f"oge15:mode:{code}:full")],
                [_button("↩ К сюжетам", "oge15:home")],
            ]
        ),
    )


async def _position_step(callback: CallbackQuery, code: str) -> None:
    await _send_selection(
        callback,
        "Выберите номер задания:",
        _keyboard(
            [
                [_button(f"№{position}", f"oge15:start:{code}:single:{position}")]
                for position in range(1, 6)
            ]
            + [
                [_button("🎲 Случайный номер", f"oge15:start:{code}:single:random")],
                [_button("↩ К сюжетам", "oge15:home")],
            ]
        ),
    )


async def render_session(
    message: Message,
    store: ScenarioPostgresRepository,
    session: ScenarioSession,
    *,
    show_assets: bool,
    user_id_override: int | None = None,
) -> None:
    snapshot = session.snapshot
    question = next(
        item for item in snapshot.questions if item.position == session.current_position
    )
    story = STORY_NAMES.get(snapshot.story_code, snapshot.story_code)
    if show_assets:
        await message.answer(snapshot.shared_context)
        adapter = public_registry().adapter(snapshot.story_code)
        for asset in snapshot.assets:
            if snapshot.story_code in {"STOVE", "FLAT"} and asset.content_type == "image/svg+xml":
                # These adapters store an SVG companion for each PNG.
                continue
            data = restore_asset_bytes(adapter.renderer, snapshot, asset)
            extension = "png" if asset.content_type == "image/png" else "svg"
            upload = BufferedInputFile(data, filename=f"scenario.{extension}")
            if asset.content_type == "image/png":
                await message.answer_photo(upload, caption=f"Общая схема · {story}")
            else:
                await message.answer_document(upload, caption=f"Общая схема · {story}")
    progress = (
        f"Задание №{session.current_position} из 5"
        if session.mode is PracticeMode.FULL
        else f"Задание №{session.current_position}"
    )
    telegram_user_id = user_id_override or (
        message.from_user.id if message.from_user else 0
    )
    rows: list[list[InlineKeyboardButton]] = []
    callback_prefix = (
        f"oge15:act:{session.session_id}:{session.current_position}:{session.navigation_revision}"
    )
    if session.question_status == "active":
        rows.extend(
            [
                [_button("💡 Подсказка", f"{callback_prefix}:hint")],
                [_button("📘 Разбор", f"{callback_prefix}:solution")],
                [_button("⏭ Пропустить", f"{callback_prefix}:skip")],
            ]
        )
    else:
        if session.mode is PracticeMode.FULL and session.current_position < 5:
            rows.append([_button("➡ Следующий вопрос", f"{callback_prefix}:next")])
        else:
            rows.append([_button("Завершить", f"{callback_prefix}:next")])
    rows.append([_button("⏸ Пауза", f"{callback_prefix}:pause")])
    title = f"{story} · {progress}"
    if session.question_status == "active":
        body = (
            f"{title}\n\n{question.condition}\n\n"
            f"Осталось попыток: {2 - session.attempt_count}. Напишите ответ в чат."
        )
    else:
        body = f"{title} · вопрос завершён"
    controls = await message.answer(body, reply_markup=_keyboard(rows))
    if session.question_status == "active":
        await store.set_condition_message(
            telegram_user_id, session.session_id, session.current_position, controls.message_id
        )
    await store.set_control_message(
        telegram_user_id,
        session.session_id,
        session.navigation_revision,
        controls.message_id,
    )


async def _start_session(
    callback: CallbackQuery,
    store: ScenarioPostgresRepository,
    repository: Repository | None,
    code: str,
    mode: PracticeMode,
    position_text: str | None,
) -> None:
    user_id = callback.from_user.id
    if not _has_user(user_id) or not isinstance(callback.message, Message):
        await answer_callback(callback, "Практические задания №1–5 сейчас недоступны.")
        return
    if await store.resume_session(user_id) is not None:
        await answer_callback(callback, "Сначала продолжите или завершите текущую практику.")
        return
    position = None if position_text is None or position_text == "random" else int(position_text)
    request = PracticeRequest(
        mode, secrets.randbelow(2**63), None if code == "RANDOM" else code, position
    )
    try:
        plan = build_practice_plan(request, public_registry())
    except (ScenarioUnavailable, ValueError):
        await answer_callback(callback, "Для этого сюжета сейчас нет доступного набора.")
        return
    try:
        session = await store.start_session(
            user_id, plan.snapshot, plan.mode, plan.selected_positions
        )
    except UniqueViolationError:
        await answer_callback(callback, "У вас уже открыта практика №1–5.")
        return
    if repository is not None:
        await repository.save_user_state(user_id, "oge15")
    await callback.message.answer(f"Вы выбрали: {STORY_NAMES[plan.snapshot.story_code]}.")
    await render_session(
        callback.message, store, session, show_assets=True, user_id_override=user_id
    )
    await answer_callback(callback)


def _valid_answer_format(story: str, policy_id: str, text: str) -> bool:
    value = text.strip()
    if story in {"STOVE", "FLAT", "TARIFF"} and policy_id != "digit_sequence_exact_3":
        value = value.replace(" ", "")
    if story == "TARIFF":
        value = value.replace("\ ", "")

    if policy_id == "paper.mapping_four":
        return bool(re.fullmatch(r"[1-4]{4}", value)) and len(set(value)) == 4
    if policy_id == "digit_sequence_exact_3":
        return bool(re.fullmatch(r"[1-3]{3}", value))
    if policy_id.endswith("months-minutes"):
        return bool(re.fullmatch(r"\d{4,8}", value))
    if policy_id in {"paper.ratio_tenths", "paper.diagonal_ratio_tenths"}:
        return bool(re.fullmatch(r"\d+[.,]\d", value))
    if story == "PAPER":
        return bool(re.fullmatch(r"[1-9]\d*", value))
    if story == "GARDEN":
        return bool(re.fullmatch(r"\d+", value))
    if story in {"FLAT", "TARIFF"}:
        return bool(re.fullmatch(r"\d+(?:[.,]\d{1,2})?", value))
    if story == "STOVE":
        return bool(re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", value))
    # The current pilot policies expect decimal notation rather than slash fractions.
    return bool(re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", value))


async def answer_message(
    message: Message,
    oge15_repository: ScenarioPostgresRepository | None = None,
    repository: Repository | None = None,
) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not _has_user(user_id) or user_id is None or message.text is None:
        raise SkipHandler
    if oge15_repository is None or repository is None:
        raise SkipHandler
    if await repository.user_state(user_id) != "oge15":
        raise SkipHandler
    store = oge15_repository
    session = await store.resume_session(user_id)
    if session is None or session.status != "active":
        raise SkipHandler
    if session.question_status != "active":
        await message.answer("Задание завершено. Используйте кнопки под результатом.")
        return
    if not matches_current_condition(
        message, {"problem_prompt_message_id": session.prompt_message_id}
    ):
        return
    question = next(
        item for item in session.snapshot.questions if item.position == session.current_position
    )
    adapter = public_registry().adapter(session.snapshot.story_code)
    policy = adapter.answer_policies[(question.answer_policy_id, question.answer_policy_version)]
    if not _valid_answer_format(
        session.snapshot.story_code, question.answer_policy_id, message.text
    ):
        await message.answer("Введите ответ в формате, указанном в условии.")
        return
    is_correct = policy.accepts(message.text, question.canonical_answer)
    result = await store.record_attempt(
        telegram_user_id=user_id,
        session_id=session.session_id,
        position=session.current_position,
        telegram_message_id=message.message_id,
        reply_to_message_id=(
            message.reply_to_message.message_id if message.reply_to_message else None
        ),
        raw_answer=message.text,
        normalized_answer=message.text.strip(),
        is_correct=is_correct,
    )
    if result is not AttemptResult.ACCEPTED:
        return
    updated = await store.resume_session(user_id)
    if updated is None:
        return
    if is_correct:
        await message.answer("Верно!")
    elif updated.question_status == "failed":
        await message.answer(f"Попытки закончились. Ответ: {question.canonical_answer}.")
    else:
        await message.answer("Неверно. Осталась одна попытка.")
        return
    await render_session(message, store, updated, show_assets=False)


async def handle_callback(
    callback: CallbackQuery,
    oge15_repository: ScenarioPostgresRepository | None = None,
    repository: Repository | None = None,
) -> None:
    if not _has_user(callback.from_user.id):
        await answer_callback(callback, "Практические задания №1–5 сейчас недоступны.")
        return
    if oge15_repository is None:
        await answer_callback(callback, "Практические задания №1–5 сейчас недоступны.")
        return
    data = callback.data or ""
    if data == "oge15:home":
        if repository is not None:
            await repository.save_user_state(callback.from_user.id, "oge15_menu")
        await _send_selection(callback, "Выберите сюжет:", _story_keyboard())
        return
    if data == "oge15:stats":
        stats = await oge15_repository.position_stats(callback.from_user.id)
        lines = ["Статистика практики №1–5:"]
        for position in range(6):
            row = stats.get(position, {})
            label = "Всего" if position == 0 else f"№{position}"
            lines.append(
                f"{label}: выдано {row.get('issued', 0)}, верно {row.get('correct', 0)}, "
                f"пропущено {row.get('skipped', 0)}"
            )
        await _send_selection(callback, "\n".join(lines), _story_keyboard())
        return
    parts = data.split(":")
    if len(parts) == 3 and parts[:2] == ["oge15", "story"]:
        await _story_step(callback, parts[2])
        return
    if len(parts) == 4 and parts[:2] == ["oge15", "mode"] and parts[3] in {"single", "full"}:
        code, mode = parts[2], PracticeMode(parts[3])
        if code != "RANDOM" and code not in STORY_NAMES:
            await answer_callback(callback, "Этот сюжет недоступен.")
        elif mode is PracticeMode.SINGLE:
            await _position_step(callback, code)
        else:
            await _start_session(callback, oge15_repository, repository, code, mode, None)
        return
    if len(parts) == 5 and parts[:2] == ["oge15", "start"] and parts[3] == "single":
        if parts[2] not in {*STORY_NAMES, "RANDOM"} or parts[4] not in {
            *map(str, range(1, 6)),
            "random",
        }:
            await answer_callback(callback, "Этот выбор недоступен.")
        else:
            await _start_session(
                callback, oge15_repository, repository, parts[2], PracticeMode.SINGLE, parts[4]
            )
        return
    if len(parts) == 6 and parts[:2] == ["oge15", "act"]:
        try:
            session_id, position, revision = UUID(parts[2]), int(parts[3]), int(parts[4])
        except ValueError:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        if not isinstance(callback.message, Message):
            await answer_callback(callback)
            return
        action = parts[5]
        session = await oge15_repository.resume_session(callback.from_user.id)
        if session is None or session.session_id != session_id:
            await answer_callback(callback, "Это занятие уже завершено.")
            return
        if position not in range(1, 6) or action not in {
            "hint",
            "solution",
            "skip",
            "next",
            "pause",
            "resume",
        }:
            await answer_callback(callback, "Это меню устарело. Откройте /start.")
            return
        question = next(
            (item for item in session.snapshot.questions if item.position == position), None
        )
        if question is None:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        accepted = await oge15_repository.apply_callback(
            telegram_user_id=callback.from_user.id,
            callback_query_id=callback.id,
            session_id=session_id,
            control_message_id=callback.message.message_id,
            expected_revision=revision,
            expected_position=position,
            action=action,
            hint_count=len(question.hints),
        )
        if not accepted:
            await answer_callback(callback, "Это действие уже обработано или задание сменилось.")
            return
        updated = await oge15_repository.resume_session(callback.from_user.id)
        await answer_callback(callback)
        if updated is None:
            if action in {"next", "skip"} and isinstance(callback.message, Message):
                await callback.message.answer(
                    "Практика завершена. Статистика доступна по команде /oge15."
                )
            return
        if action == "hint":
            q = next(q for q in updated.snapshot.questions if q.position == position)
            await callback.message.answer(q.hints[min(updated.hints_used - 1, len(q.hints) - 1)])
        elif action == "solution":
            q = next(q for q in updated.snapshot.questions if q.position == position)
            await callback.message.answer(
                "Разбор (самостоятельное решение не засчитывается):\n" + "\n".join(q.solution_steps)
            )
        elif action == "pause":
            if repository is not None:
                await repository.save_user_state(callback.from_user.id, "main_menu")
            await callback.message.answer(
                "Практика поставлена на паузу.",
                reply_markup=_keyboard(
                    [
                        [_button("▶ Продолжить", f"oge15:resume:{session_id}")],
                        [_button("↩ К сюжетам", "oge15:home")],
                    ]
                ),
            )
            return
        await render_session(
            callback.message,
            oge15_repository,
            updated,
            show_assets=False,
            user_id_override=callback.from_user.id,
        )
        return
    if len(parts) == 3 and parts[:2] == ["oge15", "resume"]:
        try:
            session_id = UUID(parts[2])
        except ValueError:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        session = await oge15_repository.resume_paused(callback.from_user.id, session_id)
        if session is None:
            await answer_callback(callback, "Сейчас нечего продолжать.")
            return
        await answer_callback(callback)
        if isinstance(callback.message, Message):
            if repository is not None:
                await repository.save_user_state(callback.from_user.id, "oge15")
            await render_session(
                callback.message,
                oge15_repository,
                session,
                show_assets=False,
                user_id_override=callback.from_user.id,
            )
        return
    await answer_callback(callback, "Это меню устарело. Откройте /start.")
