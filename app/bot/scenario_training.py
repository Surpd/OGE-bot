"""Telegram UX for public OGE 1–5 scenario sessions."""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import replace
from functools import lru_cache
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.callbacks import answer_callback
from app.bot.menu import main_menu
from app.bot.presentation import has_mathematics, send_text
from app.bot.training_ux import matches_current_condition, resumed_result
from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    ScenarioUnavailable,
    discover_story_registry,
)
from app.math.scenarios.mobile_photos import scenario_photos_for_question
from app.math.scenarios.recent_questions import is_recent_fixed_single, rotated_plan
from app.persistence.repository import Repository
from app.persistence.rotation_history import recent_story_families
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
_ACTION_CODES = {
    "hint": "h",
    "solution": "s",
    "skip": "k",
    "next": "n",
    "pause": "p",
    "data": "d",
    "finish": "f",
    "finish_request": "r",
    "finish_cancel": "c",
}
_CODE_ACTIONS = {code: action for action, code in _ACTION_CODES.items()}


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


def _action_callback(session_id: UUID, position: int, revision: int, action: str) -> str:
    """Keep scenario callbacks below Telegram's 64-byte limit."""
    code = _ACTION_CODES[action]
    return f"o:a:{session_id}:{position}:{revision}:{code}"


def _has_user(user_id: int | None) -> bool:
    return user_id is not None and user_id > 0


def _story_keyboard(selected_number: int | None = None) -> InlineKeyboardMarkup:
    suffix = f":n{selected_number}" if selected_number is not None else ""
    rows = [
        [_button(name, f"oge15:story:{code}{suffix}")]
        for code, name in STORY_NAMES.items()
    ]
    rows.extend(
        (
            [_button("🎲 Случайный сюжет", f"oge15:story:RANDOM{suffix}")],
            [_button("📂 Незавершённые тренировки", "oge15:unfinished")],
        )
    )
    if selected_number is not None:
        rows.append(
            [_button(f"↩ К статистике №{selected_number}", f"oge15:return:{selected_number}")]
        )
    else:
        rows.append([_button("↩ В меню", "nav:main")])
    return _keyboard(rows)


async def show_public_oge15(
    message: Message,
    oge15_repository: ScenarioPostgresRepository | None = None,
    repository: Repository | None = None,
    *,
    selected_number: int | None = None,
) -> None:
    user_id = message.from_user.id if message.from_user else None
    if not _has_user(user_id):
        return
    if oge15_repository is None:
        await message.answer("Практические задания №1–5 пока недоступны.")
        return
    if repository is not None and user_id is not None:
        await oge15_repository.pause_foreground(user_id)
        await repository.save_user_state(user_id, "oge15_menu")
    text = (
        f"Практика №{selected_number} · выберите сюжет:"
        if selected_number is not None
        else "Практические задания №1–5\nВыберите сюжет:"
    )
    if repository is None:
        await message.answer(text, reply_markup=_story_keyboard(selected_number))
    else:
        await send_text(
            message,
            repository,
            text,
            reply_markup=_story_keyboard(selected_number),
            user_id_override=user_id,
        )


async def _send_selection(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
    repository: Repository | None = None,
) -> None:
    if isinstance(callback.message, Message):
        if repository is None:
            await callback.message.answer(text, reply_markup=keyboard)
        else:
            await send_text(
                callback.message,
                repository,
                text,
                reply_markup=keyboard,
                user_id_override=callback.from_user.id,
            )
    await answer_callback(callback)


async def _session_choice(
    callback: CallbackQuery,
    session: ScenarioSession,
    repository: Repository | None = None,
    return_number: int | None = None,
) -> None:
    story = STORY_NAMES.get(session.snapshot.story_code, session.snapshot.story_code)
    lesson = "пятёрку" if session.mode is PracticeMode.FULL else "одно задание"
    new_label = "🆕 Новая пятёрка" if session.mode is PracticeMode.FULL else "🆕 Новое задание"
    back_button = (
        _button(f"↩ К статистике №{return_number}", f"oge15:return:{return_number}")
        if return_number is not None
        else _button("↩ К сюжетам", "oge15:home")
    )
    await _send_selection(
        callback,
        f"Сохранена тренировка «{story}» — {lesson}, №{session.current_position}.",
        _keyboard(
            [
                [_button(f"▶ Продолжить · {lesson} · №{session.current_position}",
                         f"oge15:resume:{session.session_id}")],
                [_button(new_label, f"oge15:restart:{session.session_id}")],
                [back_button],
            ]
        ),
        repository,
    )


async def _story_step(
    callback: CallbackQuery,
    code: str,
    store: ScenarioPostgresRepository,
    repository: Repository | None,
    requested_position: int | None = None,
) -> None:
    if code != "RANDOM" and code not in STORY_NAMES:
        await answer_callback(callback, "Этот сюжет недоступен.")
        return
    title = "Случайный сюжет" if code == "RANDOM" else STORY_NAMES[code]
    if requested_position is not None:
        if code == "RANDOM":
            await _start_session(
                callback, store, repository, code, PracticeMode.SINGLE, str(requested_position)
            )
            return
        saved_session = await store.find_open_session(
            callback.from_user.id, code, PracticeMode.SINGLE
        )
        if saved_session is not None:
            if saved_session.current_position == requested_position:
                await _session_choice(
                    callback, saved_session, repository, return_number=requested_position
                )
            else:
                await _send_selection(
                    callback,
                    f"Для сюжета «{title}» сохранено одно задание "
                    f"№{saved_session.current_position}. "
                    f"Для статистики выбран №{requested_position}.",
                    _keyboard(
                        [
                            [
                                _button(
                                    "▶ Продолжить сохранённое",
                                    f"oge15:resume:{saved_session.session_id}",
                                )
                            ],
                            [_button(
                                f"🆕 Начать задание №{requested_position}",
                                f"oge15:new:{code}:{requested_position}",
                            )],
                            [_button(f"↩ К статистике №{requested_position}",
                                     f"oge15:return:{requested_position}")],
                        ]
                    ),
                    repository,
                )
            return
        await _start_session(
            callback, store, repository, code, PracticeMode.SINGLE, str(requested_position)
        )
        return
    if code != "RANDOM":
        saved_sessions = [
            session for session in await store.list_open_sessions(callback.from_user.id)
            if session.snapshot.story_code == code
        ]
        if saved_sessions:
            rows: list[list[InlineKeyboardButton]] = []
            for session in saved_sessions:
                lesson = "пятёрка" if session.mode is PracticeMode.FULL else "одно задание"
                rows.append([_button(
                    f"▶ Продолжить · {lesson} · №{session.current_position}",
                    f"oge15:resume:{session.session_id}",
                )])
            rows.extend((
                [_button("Выбрать одно задание", f"oge15:mode:{code}:single")],
                [_button("Вся пятёрка", f"oge15:mode:{code}:full")],
                [_button("↩ К сюжетам", "oge15:home")],
            ))
            await _send_selection(
                callback,
                f"Сюжет: {title}. Сохранённые тренировки можно продолжить или начать заново.",
                _keyboard(rows),
                repository,
            )
            return
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
        repository,
    )


async def _position_step(
    callback: CallbackQuery, code: str, repository: Repository | None = None
) -> None:
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
        repository,
    )


def scenario_context_for_question(snapshot: ScenarioSnapshot, position: int) -> str:
    context = snapshot.shared_context
    question = next(
        item for item in snapshot.questions if item.position == position
    )
    if snapshot.story_code == "TYRES":
        context = "\n".join(line for line in context.splitlines() if not line.startswith("|"))
        context = context.replace("**", "")
    elif snapshot.story_code == "PAPER":
        context = context.partition("Таблица размеров")[0].rstrip()
    elif snapshot.story_code == "STOVE":
        context = context.partition("Печь | Тип |")[0].rstrip()
    elif snapshot.story_code == "TARIFF":
        context = "\n".join(
            line for line in context.splitlines()
            if not line.startswith((
                "Минуты по месяцам:", "Мобильный интернет по месяцам:",
            ))
        )
    elif snapshot.story_code == "GARDEN" and snapshot.generator_version in {
        "garden-sosnovka-1.0", "garden-sosnovka-1.1",
    }:
        context += (
            "\nДом с выступом у верхней границы. Баня ниже яблонь слева, "
            "гараж ниже ворот справа, теплица внутри огорода."
        )
    elif snapshot.story_code == "GARDEN" and question.family_id != "GARDEN-09-HEAT-BREAKEVEN":
        prefix, separator, remainder = context.partition("Отопление одного дома")
        if separator:
            _, shared_questions, closing = remainder.partition("Все пять вопросов")
            context = prefix + ("\nВсе пять вопросов" + closing if shared_questions else "")
    elif snapshot.story_code == "FLAT":
        context = context.replace("Это собственная SVG/PNG схема фиксированной топологии.", "")
        if "первая лоджия" in snapshot.questions[2].condition:
            context += " На плане первая лоджия расположена слева."
    return context


async def _show_data(
    message: Message, session: ScenarioSession, *, shared: bool, current: bool,
    repository: Repository | None = None, user_id: int | None = None,
) -> None:
    snapshot = session.snapshot
    story = STORY_NAMES[snapshot.story_code]
    if shared:
        context = scenario_context_for_question(snapshot, session.current_position)
        if repository is None:
            await message.answer(context)
        else:
            await send_text(message, repository, context, user_id_override=user_id)
    if shared or current:
        photos = scenario_photos_for_question(snapshot, session.current_position)
    else:
        photos = ()
    for index, data in enumerate(photos, 1):
        upload = BufferedInputFile(data, filename=f"scenario-{index}.png")
        await message.answer_photo(upload, caption=f"Данные задачи · {story}")


async def _retire_unsafe(
    message: Message, store: ScenarioPostgresRepository, user_id: int, session: ScenarioSession
) -> bool:
    if not await store.close_legacy_with_exposed_answer(user_id, session):
        return False
    await message.answer(
        "Эта практика завершена: в старой версии задания часть ответа была видна заранее. "
        "История сохранена. Начните новую практику через /oge15."
    )
    return True


async def render_session(
    message: Message,
    store: ScenarioPostgresRepository,
    session: ScenarioSession,
    *,
    show_assets: bool,
    show_current_asset: bool = False,
    edit_current: bool = False,
    result_text: str | None = None,
    user_id_override: int | None = None,
    repository: Repository | None = None,
) -> None:
    telegram_user_id = user_id_override or (message.from_user.id if message.from_user else 0)
    if await _retire_unsafe(message, store, telegram_user_id, session):
        return
    snapshot = session.snapshot
    question = next(
        item for item in snapshot.questions if item.position == session.current_position
    )
    story = STORY_NAMES.get(snapshot.story_code, snapshot.story_code)
    if show_assets or show_current_asset:
        await _show_data(message, session, shared=show_assets, current=True,
                         repository=repository, user_id=telegram_user_id)
    progress = (
        f"Задание №{session.current_position} из 5"
        if session.mode is PracticeMode.FULL
        else f"Задание №{session.current_position}"
    )
    rows: list[list[InlineKeyboardButton]] = []

    def callback(action: str) -> str:
        return _action_callback(
            session.session_id,
            session.current_position,
            session.navigation_revision,
            action,
        )

    if session.question_status == "active":
        rows.extend(
            [
                [
                    _button("💡 Подсказка", callback("hint")),
                    _button("📘 Разбор", callback("solution")),
                ],
                [
                    _button("⏭ Пропустить", callback("skip")),
                    _button("📷 Схема / данные", callback("data")),
                ],
            ]
        )
        finish_button = (
            _button("⏹ Завершить", callback("finish_request"))
            if session.mode is PracticeMode.FULL
            else None
        )
        rows.append(
            [
                _button("↩ В меню", callback("pause")),
                *([finish_button] if finish_button is not None else []),
            ]
        )
    else:
        if session.mode is PracticeMode.FULL and session.current_position < 5:
            next_label = "➡ Следующий вопрос"
        elif session.mode is PracticeMode.FULL:
            next_label = "Завершить пятёрку"
        else:
            next_label = "Завершить"
        rows.append(
            [
                _button(next_label, callback("next")),
                _button("📷 Схема / данные", callback("data")),
            ]
        )
        rows.append([_button("↩ В меню", callback("pause"))])
    title = f"{story} · {progress}"
    if session.question_status == "active":
        body = (
            f"{title}\n\n{question.condition}\n\n"
            "Напишите ответ в чат."
        )
    else:
        body = f"{title}\n\n{question.condition}"
        if result_text is None:
            result_text = resumed_result(
                session.question_status, {"correct_answer": question.canonical_answer}
            )
    if result_text:
        body += f"\n\n{result_text}"
    markup = _keyboard(rows)
    controls = None
    if (edit_current and message.message_id == session.control_message_id
            and (repository is None or not has_mathematics(body))):
        try:
            edited = await message.edit_text(body, reply_markup=markup)
            if isinstance(edited, Message):
                controls = edited
        except TelegramBadRequest:
            pass
    if controls is None:
        if repository is not None:
            controls = await send_text(
                message,
                repository,
                body,
                reply_markup=markup,
                user_id_override=telegram_user_id,
            )
        else:
            controls = await message.answer(body, reply_markup=markup)
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


async def _render_finish_confirmation(
    message: Message,
    store: ScenarioPostgresRepository,
    session: ScenarioSession,
    user_id: int,
) -> None:
    story = STORY_NAMES.get(session.snapshot.story_code, session.snapshot.story_code)
    body = (
        f"Завершить тренировку «{story}» сейчас?\n\n"
        "Результаты уже выданных заданий сохранятся. "
        "Невыданные задания не считаются ошибками или пропусками."
    )
    markup = _keyboard(
        [[
            _button(
                "⏹ Завершить",
                _action_callback(
                    session.session_id,
                    session.current_position,
                    session.navigation_revision,
                    "finish",
                ),
            ),
            _button(
                "↩ Продолжить",
                _action_callback(
                    session.session_id,
                    session.current_position,
                    session.navigation_revision,
                    "finish_cancel",
                ),
            ),
        ]]
    )
    try:
        edited = await message.edit_text(body, reply_markup=markup)
        controls = edited if isinstance(edited, Message) else message
    except TelegramBadRequest:
        controls = await message.answer(body, reply_markup=markup)
    await store.set_control_message(
        user_id, session.session_id, session.navigation_revision, controls.message_id
    )


async def _start_session(
    callback: CallbackQuery,
    store: ScenarioPostgresRepository,
    repository: Repository | None,
    code: str,
    mode: PracticeMode,
    position_text: str | None,
    *,
    replace_session_id: UUID | None = None,
) -> None:
    user_id = callback.from_user.id
    if not _has_user(user_id) or not isinstance(callback.message, Message):
        await answer_callback(callback, "Практические задания №1–5 сейчас недоступны.")
        return
    position = None if position_text is None or position_text == "random" else int(position_text)
    story_code = None if code == "RANDOM" else code
    recent = await store.recent_questions(user_id)
    try:
        plan = await asyncio.to_thread(
            rotated_plan, PracticeRequest(mode, secrets.randbelow(2**63), story_code, position),
            public_registry(), await recent_story_families(store, user_id), recent,
        )
    except (ScenarioUnavailable, ValueError):
        await answer_callback(callback, "Для этого сюжета сейчас нет доступного набора.")
        return
    if is_recent_fixed_single(plan, recent):
        await answer_callback(
            callback, "Этот вариант уже был недавно. Выберите другой номер или сюжет.",
            show_alert=True,
        )
        return
    session = await store.start_session(
        user_id,
        plan.snapshot,
        plan.mode,
        plan.selected_positions,
        replace_session_id=replace_session_id,
    )
    if session is None:
        existing = await store.find_open_session(
            user_id, plan.snapshot.story_code, plan.mode
        )
        if existing is not None:
            return_number = (
                int(position_text)
                if mode is PracticeMode.SINGLE
                and position_text is not None
                and position_text.isascii()
                and position_text.isdigit()
                else None
            )
            await _session_choice(callback, existing, repository, return_number)
        else:
            await answer_callback(callback, "Это занятие уже изменилось. Выберите сюжет ещё раз.")
        return
    await render_session(
        callback.message, store, session, show_assets=True, user_id_override=user_id,
        repository=repository,
    )
    if repository is not None:
        await repository.save_user_state(user_id, "oge15")
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
    if await _retire_unsafe(message, store, user_id, session):
        return
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
    updated = await store.resume_session(user_id, session.session_id)
    if updated is None or updated.status != "active":
        return
    if is_correct:
        result_text = "✅ Верно! Ответ засчитан."
    elif updated.question_status == "failed":
        result_text = (
            f"Правильный ответ: {question.canonical_answer}.\n\n"
            + "\n".join(question.solution_steps)
        )
    else:
        await message.answer("Пока неверно. Попробуйте ещё раз.")
        return
    await render_session(
        message, store, updated, show_assets=False, result_text=result_text, repository=repository
    )


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
    data = data.partition("~")[0]
    if "~" in (callback.data or "") and repository is not None:
        if not await repository.claim_navigation_message(
            callback.from_user.id,
            callback.message.message_id if isinstance(callback.message, Message) else 0,
            (callback.data or "").rpartition("~")[2],
        ):
            await answer_callback(callback, "Это меню устарело. Откройте актуальную страницу.")
            return
    if data == "oge15:home":
        if repository is not None:
            await repository.save_user_state(callback.from_user.id, "oge15_menu")
        await _send_selection(callback, "Выберите сюжет:", _story_keyboard(), repository)
        return
    if data == "oge15:stats":
        from app.bot.progress import progress_navigation

        if isinstance(callback.message, Message) and repository is not None:
            await progress_navigation(
                callback.message, repository, callback.from_user.id, "summary"
            )
            await answer_callback(callback)
        return
    if data.startswith("oge15:return:"):
        value = data.removeprefix("oge15:return:")
        if value.isascii() and value.isdigit() and int(value) in range(1, 6):
            from app.bot.progress import progress_navigation

            if isinstance(callback.message, Message) and repository is not None:
                await progress_navigation(
                    callback.message, repository, callback.from_user.id, f"number:{value}"
                )
                await answer_callback(callback)
            return
    if data == "oge15:unfinished" or data.startswith("oge15:unfinished:"):
        raw_page = data.removeprefix("oge15:unfinished:") if data.count(":") == 2 else "0"
        if not raw_page.isascii() or not raw_page.isdigit() or len(raw_page) > 2:
            await answer_callback(callback, "Эта страница недоступна.")
            return
        sessions = await oge15_repository.list_open_sessions(callback.from_user.id)
        if not sessions:
            await _send_selection(
                callback,
                "Нет незавершённых тренировок.",
                _story_keyboard(),
                repository,
            )
            return
        pages = (len(sessions) + 5) // 6
        page = min(int(raw_page), pages - 1)
        start = page * 6
        legend = []
        buttons = []
        for index, saved in enumerate(sessions[start:start + 6], start + 1):
            story = STORY_NAMES.get(saved.snapshot.story_code, saved.snapshot.story_code)
            mode = "пятёрка" if saved.mode is PracticeMode.FULL else "одно задание"
            legend.append(f"{index}. {story} · {mode} · №{saved.current_position}")
            buttons.append(_button(str(index), f"oge15:resume:{saved.session_id}"))
        rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        arrows = []
        if page:
            arrows.append(_button("←", f"oge15:unfinished:{page - 1}"))
        if page + 1 < pages:
            arrows.append(_button("→", f"oge15:unfinished:{page + 1}"))
        if arrows:
            rows.append(arrows)
        rows.append([_button("↩ К сюжетам", "oge15:home")])
        await _send_selection(
            callback, "Ваши незавершённые тренировки\n\n" + "\n".join(legend),
            _keyboard(rows), repository,
        )
        return
    if data.startswith("oge15:rc:"):
        data = data.replace("oge15:rc:", "oge15:restart-confirm:", 1)
    elif data.startswith("oge15:rx:"):
        data = data.replace("oge15:rx:", "oge15:restart-cancel:", 1)
    parts = data.split(":")
    if len(parts) == 3 and parts[:2] == ["oge15", "story"]:
        await _story_step(callback, parts[2], oge15_repository, repository)
        return
    if len(parts) == 4 and parts[:2] == ["oge15", "story"]:
        selected_position = parts[3][1:] if parts[3].startswith("n") else ""
        if (
            selected_position.isascii()
            and selected_position.isdigit()
            and int(selected_position) in range(1, 6)
        ):
            await _story_step(
                callback, parts[2], oge15_repository, repository, int(selected_position)
            )
        else:
            await answer_callback(callback, "Этот выбор устарел.")
        return
    if len(parts) == 4 and parts[:2] == ["oge15", "new"]:
        code, position_text = parts[2], parts[3]
        if (
            code not in STORY_NAMES
            or not position_text.isascii()
            or not position_text.isdigit()
            or int(position_text) not in range(1, 6)
        ):
            await answer_callback(callback, "Этот выбор недоступен.")
            return
        existing = await oge15_repository.find_open_session(
            callback.from_user.id, code, PracticeMode.SINGLE
        )
        if existing is None:
            await _start_session(
                callback, oge15_repository, repository, code, PracticeMode.SINGLE, position_text
            )
            return
        await _send_selection(
            callback,
            f"Начать задание №{position_text} сюжета «{STORY_NAMES[code]}»? "
            "Текущее занятие сохранено в истории.",
            _keyboard(
                [
                    [_button("🆕 Подтвердить", f"oge15:new-confirm:{code}:{position_text}")],
                    [_button(f"↩ К статистике №{position_text}", f"oge15:return:{position_text}")],
                ]
            ),
            repository,
        )
        return
    if len(parts) == 4 and parts[:2] == ["oge15", "new-confirm"]:
        code, position_text = parts[2], parts[3]
        if (
            code not in STORY_NAMES
            or not position_text.isascii()
            or not position_text.isdigit()
            or int(position_text) not in range(1, 6)
        ):
            await answer_callback(callback, "Этот выбор устарел.")
            return
        existing = await oge15_repository.find_open_session(
            callback.from_user.id, code, PracticeMode.SINGLE
        )
        if existing is None:
            await answer_callback(callback, "Это занятие уже изменилось. Выберите сюжет ещё раз.")
            return
        await answer_callback(callback)
        await _start_session(
            callback,
            oge15_repository,
            repository,
            code,
            PracticeMode.SINGLE,
            position_text,
            replace_session_id=existing.session_id,
        )
        return
    if len(parts) == 4 and parts[:2] == ["oge15", "mode"] and parts[3] in {"single", "full"}:
        code, mode = parts[2], PracticeMode(parts[3])
        if code != "RANDOM" and code not in STORY_NAMES:
            await answer_callback(callback, "Этот сюжет недоступен.")
        elif mode is PracticeMode.SINGLE:
            selected_session = (
                await oge15_repository.find_open_session(callback.from_user.id, code, mode)
                if code != "RANDOM" else None
            )
            if selected_session is None:
                await _position_step(callback, code, repository)
            else:
                await _session_choice(callback, selected_session, repository)
        else:
            selected_session = (
                await oge15_repository.find_open_session(callback.from_user.id, code, mode)
                if code != "RANDOM" else None
            )
            if selected_session is None:
                await _start_session(callback, oge15_repository, repository, code, mode, None)
            else:
                await _session_choice(callback, selected_session, repository)
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
    if len(parts) == 6 and parts[:2] in (["oge15", "act"], ["o", "a"]):
        try:
            session_id, action_position, revision = UUID(parts[2]), int(parts[3]), int(parts[4])
        except ValueError:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        if not isinstance(callback.message, Message):
            await answer_callback(callback)
            return
        action = _CODE_ACTIONS.get(parts[5], "") if parts[:2] == ["o", "a"] else parts[5]
        session = await oge15_repository.resume_session(callback.from_user.id, session_id)
        if session is None:
            await answer_callback(callback, "Это занятие уже завершено.")
            return
        if action_position not in range(1, 6) or action not in {
            "hint",
            "solution",
            "skip",
            "next",
            "pause",
            "data",
            "finish",
            "finish_request",
            "finish_cancel",
        }:
            await answer_callback(callback, "Это меню устарело. Откройте /start.")
            return
        question = next(
            (item for item in session.snapshot.questions if item.position == action_position), None
        )
        if question is None:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        if (
            session.current_position == action_position
            and session.navigation_revision == revision
            and session.control_message_id == callback.message.message_id
            and await _retire_unsafe(
                callback.message, oge15_repository, callback.from_user.id, session
            )
        ):
            await answer_callback(callback)
            return
        accepted = await oge15_repository.apply_callback(
            telegram_user_id=callback.from_user.id,
            callback_query_id=callback.id,
            session_id=session_id,
            control_message_id=callback.message.message_id,
            expected_revision=revision,
            expected_position=action_position,
            action=action,
            hint_count=len(question.hints),
        )
        if not accepted:
            await answer_callback(callback, "Это действие уже обработано или задание сменилось.")
            return
        await answer_callback(callback)
        if action == "data":
            await _show_data(callback.message, session, shared=True, current=True,
                             repository=repository, user_id=callback.from_user.id)
            return
        updated = await oge15_repository.resume_session(callback.from_user.id, session_id)
        if action == "finish_request" and updated is not None:
            await _render_finish_confirmation(
                callback.message, oge15_repository, updated, callback.from_user.id
            )
            return
        if action == "finish_cancel" and updated is not None:
            await render_session(
                callback.message,
                oge15_repository,
                updated,
                show_assets=False,
                edit_current=True,
                user_id_override=callback.from_user.id,
                repository=repository,
            )
            return
        if updated is not None and updated.status != "active" and action != "pause":
            return
        if updated is None:
            if action in {"finish", "next", "skip"} and isinstance(callback.message, Message):
                summary = await oge15_repository.session_summary(session_id)
                if action == "finish":
                    heading = "Тренировка завершена досрочно."
                    note = "Невыданные вопросы не считаются ошибками или пропусками."
                elif session.mode is PracticeMode.FULL:
                    heading = "Пятёрка завершена!"
                    note = "Все пять вопросов были выданы."
                else:
                    heading = "Одно задание завершено!"
                    note = ""
                terminal_text = (
                    f"{heading}\n\n"
                    f"Верно: {summary['correct']} · ошибок после двух попыток: "
                    f"{summary['failed']}\n"
                    f"Разборов: {summary['reviewed']} · пропусков: {summary['skipped']}\n"
                    f"Задано вопросов: {summary['issued']}.\n{note}"
                ).rstrip()
                if repository is not None:
                    from app.bot.navigation import (
                        bind_navigation,
                        navigation_revision,
                        prepare_navigation_markup,
                    )

                    await repository.save_user_state(callback.from_user.id, "main_menu")
                    markup = prepare_navigation_markup(main_menu())
                    try:
                        edited = await callback.message.edit_text(
                            terminal_text, reply_markup=cast(InlineKeyboardMarkup, markup)
                        )
                        target = edited if isinstance(edited, Message) else callback.message
                        await bind_navigation(
                            target, repository, callback.from_user.id, "main_menu",
                            navigation_revision(markup),
                        )
                    except TelegramBadRequest:
                        await send_text(
                            callback.message,
                            repository,
                            terminal_text,
                            user_id_override=callback.from_user.id,
                            reply_markup=main_menu(),
                        )
                else:
                    await callback.message.answer(terminal_text)
            return
        result_text = None
        if action == "hint":
            q = next(q for q in updated.snapshot.questions if q.position == action_position)
            hint = q.hints[min(updated.hints_used - 1, len(q.hints) - 1)]
            if repository is None:
                await callback.message.answer(hint)
            else:
                await send_text(callback.message, repository, hint,
                                user_id_override=callback.from_user.id)
        elif action == "solution":
            q = next(q for q in updated.snapshot.questions if q.position == action_position)
            result_text = "Разбор:\n" + "\n".join(q.solution_steps)
        elif action == "pause":
            if repository is not None:
                await repository.save_user_state(callback.from_user.id, "main_menu")
                await send_text(
                    callback.message,
                    repository,
                    "Главное меню.",
                    user_id_override=callback.from_user.id,
                    reply_markup=main_menu(has_session=True),
                )
            else:
                await callback.message.answer("Практика сохранена. Нажмите «Продолжить» из меню.")
            return
        await render_session(
            callback.message,
            oge15_repository,
            updated,
            show_assets=False,
            show_current_asset=action in {"next", "skip"},
            edit_current=action in {"hint", "solution"},
            result_text=result_text,
            user_id_override=callback.from_user.id,
            repository=repository,
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
            await render_session(
                callback.message,
                oge15_repository,
                session,
                show_assets=True,
                user_id_override=callback.from_user.id,
                repository=repository,
            )
            if repository is not None:
                await repository.save_user_state(callback.from_user.id, "oge15")
        return
    if len(parts) == 3 and parts[:2] == ["oge15", "restart"]:
        try:
            old_id = UUID(parts[2])
        except ValueError:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        existing = await oge15_repository.resume_session(callback.from_user.id, old_id)
        if existing is None:
            await answer_callback(callback, "Это занятие уже изменилось.")
            return
        story = STORY_NAMES.get(existing.snapshot.story_code, existing.snapshot.story_code)
        lesson = "одно задание" if existing.mode is PracticeMode.SINGLE else "всю пятёрку"
        await _send_selection(
            callback,
            f"Начать заново сюжет «{story}» — {lesson}? "
            "Сохранённые результаты останутся в истории.",
            _keyboard(
                [
                    [_button("🆕 Подтвердить", f"oge15:rc:{old_id}")],
                    [_button("↩ Отмена", f"oge15:rx:{old_id}")],
                ]
            ),
            repository,
        )
        return
    if len(parts) == 3 and parts[:2] in (
        ["oge15", "restart-confirm"], ["oge15", "restart-cancel"]
    ):
        try:
            old_id = UUID(parts[2])
        except ValueError:
            await answer_callback(callback, "Эта кнопка устарела.")
            return
        existing = await oge15_repository.resume_session(callback.from_user.id, old_id)
        if existing is None:
            await answer_callback(callback, "Это занятие уже изменилось.")
            return
        if parts[1] == "restart-cancel":
            await _session_choice(callback, existing, repository)
            return
        restart_position_text = (
            str(existing.current_position)
            if existing.mode is PracticeMode.SINGLE
            else None
        )
        await answer_callback(callback)
        await _start_session(
            callback,
            oge15_repository,
            repository,
            existing.snapshot.story_code,
            existing.mode,
            restart_position_text,
            replace_session_id=old_id,
        )
        return
    await answer_callback(callback, "Это меню устарело. Откройте /start.")
