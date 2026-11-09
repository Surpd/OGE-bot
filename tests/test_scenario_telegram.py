from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_inline_dispatcher_postgres import TelegramSession
from test_navigation_postgres import navigation_pool as postgres_db_fixture  # noqa: F401, F811

from app.bot import router, scenario_training
from app.bot.navigation import navigation_callback
from app.bot.router import build_router, choose_task12, continue_session, return_to_menu
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    restore_asset_bytes,
)
from app.persistence.repository import PostgresRepository
from app.persistence.scenario_repository import (
    AttemptResult,
    ScenarioPostgresRepository,
    ScenarioSession,
)


@pytest.fixture
async def oge15_navigation_pool(postgres_db_fixture):  # noqa: F811
    return postgres_db_fixture


@pytest.mark.asyncio
async def test_stale_and_repeated_main_callback_preserve_scenario_state(
    oge15_navigation_pool, monkeypatch
):
    repository = PostgresRepository(oge15_navigation_pool)
    store = ScenarioPostgresRepository(oge15_navigation_pool)
    user_id = int(uuid4().int % (2**62)) + 1
    user = User(id=user_id, is_bot=False, first_name="Stale menu callback")
    await repository.register_user(user_id)
    await repository.save_user_state(user_id, "main_menu")
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 61203, "TYRES"),
        scenario_training.public_registry(),
    ).snapshot
    session = await store.start_session(user_id, snapshot, PracticeMode.FULL, (1, 2, 3, 4, 5))
    assert session is not None and session.status == "active"
    await repository.save_user_state(user_id, "main_menu")
    menu_message_id = 771003
    assert await repository.set_navigation_message(
        user_id, "main_menu", menu_message_id, "current-revision"
    )

    before = await store.resume_session(user_id, session.session_id)
    assert before is not None
    before_stats = await store.position_stats(user_id)
    before_progress = await oge15_navigation_pool.fetch(
        """SELECT position, status, attempt_count, hints_used, prompt_message_id
           FROM oge15_question_progress WHERE session_id=$1 ORDER BY position""",
        session.session_id,
    )
    before_attempts = await oge15_navigation_pool.fetchval(
        "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", session.session_id
    )

    callback = AsyncMock()
    callback.data = "nav:main~old-revision"
    callback.from_user = user
    callback.message = Message(
        message_id=menu_message_id,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
    )
    await navigation_callback(callback, repository, store)
    after_stale = await store.resume_session(user_id, session.session_id)
    assert after_stale == before
    assert after_stale.status == "active"
    assert await store.position_stats(user_id) == before_stats
    stale_progress = await oge15_navigation_pool.fetch(
        """SELECT position, status, attempt_count, hints_used, prompt_message_id
           FROM oge15_question_progress WHERE session_id=$1 ORDER BY position""",
        session.session_id,
    )
    assert stale_progress == before_progress
    assert await oge15_navigation_pool.fetchval(
        "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", session.session_id
    ) == before_attempts

    # The first current menu callback may pause the foreground session. Its
    # repeated delivery must fail the one-time menu claim before any side effect.
    monkeypatch.setattr(router, "return_to_menu", AsyncMock())
    callback.data = "nav:main~current-revision"
    await navigation_callback(callback, repository, store)
    after_first = await store.resume_session(user_id, session.session_id)
    assert after_first is not None and after_first.status == "paused"
    after_first_stats = await store.position_stats(user_id)
    after_first_progress = await oge15_navigation_pool.fetch(
        """SELECT position, status, attempt_count, hints_used, prompt_message_id
           FROM oge15_question_progress WHERE session_id=$1 ORDER BY position""",
        session.session_id,
    )
    after_first_attempts = await oge15_navigation_pool.fetchval(
        "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", session.session_id
    )
    callback.data = "nav:main~current-revision"
    await navigation_callback(callback, repository, store)

    after = await store.resume_session(user_id, session.session_id)
    assert after == after_first
    assert after.session_id == before.session_id
    assert after.current_position == before.current_position
    assert after.snapshot.seed == before.snapshot.seed
    assert await store.position_stats(user_id) == after_first_stats
    after_progress = await oge15_navigation_pool.fetch(
        """SELECT position, status, attempt_count, hints_used, prompt_message_id
           FROM oge15_question_progress WHERE session_id=$1 ORDER BY position""",
        session.session_id,
    )
    assert after_progress == after_first_progress
    assert await oge15_navigation_pool.fetchval(
        "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", session.session_id
    ) == after_first_attempts



def test_oge15_public_number_menu_and_story_exclusions() -> None:
    from app.bot.menu import number_menu

    buttons = [b for row in number_menu().inline_keyboard for b in row]
    assert any(
        b.text == "№1–5 · Практические задания" and b.callback_data == "nav:oge15"
        for b in buttons
    )
    assert scenario_training._has_user(7)
    assert scenario_training._has_user(987654321)
    assert not scenario_training._has_user(None)
    assert "ROUTE" not in scenario_training.STORY_NAMES


def test_public_registry_is_explicit_and_excludes_unconfirmed_or_blocked_families() -> None:
    registry = scenario_training.public_registry()
    family_owners: dict[str, str] = {}
    policy_types: dict[tuple[str, str], type[object]] = {}
    assert registry.story_codes == ("FLAT", "GARDEN", "PAPER", "ROUTE", "STOVE", "TARIFF", "TYRES")
    assert registry.available_stories(PracticeMode.FULL) == (
        "FLAT",
        "GARDEN",
        "PAPER",
        "STOVE",
        "TARIFF",
        "TYRES",
    )
    assert registry.available_positions("ROUTE") == ()
    for code in registry.story_codes:
        adapter = registry.adapter(code)
        for family in adapter.family_registry:
            assert family.family_id not in family_owners
            family_owners[family.family_id] = code
            policy_key = (family.answer_policy_id, family.answer_policy_version)
            policy = adapter.answer_policies.get(policy_key)
            if policy is None:
                assert not family.available
                continue
            previous_type = policy_types.setdefault(policy_key, type(policy))
            assert previous_type is type(policy)
            if family.available:
                assert family.family_id in scenario_training.PUBLIC_FAMILIES[code]
                assert family.status.value == "enabled_candidate"
    # Constructing the public registry never mutates ordinary adapter defaults.
    from app.math.scenario_engine import discover_story_registry

    defaults = discover_story_registry()
    assert not defaults.available_stories(PracticeMode.FULL)
    assert all(
        not family.enabled
        for code in defaults.story_codes
        for family in defaults.adapter(code).family_registry
    )


@pytest.mark.parametrize("story_code", ("TYRES", "PAPER", "STOVE", "TARIFF", "GARDEN", "FLAT"))
def test_each_public_story_builds_single_and_full_from_one_validated_snapshot(
    story_code: str,
) -> None:
    registry = scenario_training.public_registry()
    single = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, 90125, story_code=story_code, position=3), registry
    )
    full = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 90126, story_code=story_code), registry
    )
    assert single.selected_positions == (3,)
    assert tuple(question.position for question in single.snapshot.questions) == (1, 2, 3, 4, 5)
    assert full.selected_positions == (1, 2, 3, 4, 5)
    assert {question.scenario_seed for question in full.snapshot.questions} == {full.snapshot.seed}
    adapter = registry.adapter(story_code)
    for asset in full.snapshot.assets:
        restored = restore_asset_bytes(adapter.renderer, full.snapshot, asset)
        assert sha256(restored).hexdigest() == asset.sha256


async def _feed(
    dispatcher: Dispatcher,
    bot: Bot,
    repository: PostgresRepository,
    scenario_repository: ScenarioPostgresRepository,
    update: Update,
) -> None:
    await dispatcher.feed_update(
        bot, update, repository=repository, oge15_repository=scenario_repository
    )


@pytest.mark.asyncio
async def test_dispatcher_public_oge15_full_session_answers_pause_and_resume(
    oge15_navigation_pool
) -> None:
    transport = TelegramSession()
    bot = Bot("123456:TEST", session=transport)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    repository = PostgresRepository(oge15_navigation_pool)
    scenario_repository = ScenarioPostgresRepository(oge15_navigation_pool)
    user_id = int(uuid4().int % (2**62)) + 1
    user = User(id=user_id, is_bot=False, first_name="Synthetic pilot")
    await repository.register_user(user_id)
    await repository.save_user_state(user_id, "main_menu")
    update_id = 1

    async def callback(message: Message, label: str) -> Message:
        nonlocal update_id
        data = next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if button.text == label
        )
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"pilot-callback-{update_id}",
                    from_user=user,
                    chat_instance="pilot",
                    message=message,
                    data=data,
                ),
            ),
        )
        return max(transport.messages.values(), key=lambda item: item.message_id)

    async def send(text: str, message_id: int, reply: Message | None = None) -> None:
        nonlocal update_id
        update_id += 1
        await _feed(
            dispatcher, bot, repository, scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=message_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text=text,
                    reply_to_message=reply,
                ),
            ),
        )

    def assert_terminal_since(message_id: int) -> None:
        assert all(
            "Напишите ответ" not in (item.text or "")
            for item in transport.messages.values()
            if item.message_id > message_id
        )

    try:
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=1,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text="/oge15",
                ),
            ),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await callback(menu, "Шины")
        menu = await callback(menu, "Вся пятёрка")
        session = await scenario_repository.resume_session(user_id)
        assert session is not None and session.mode is PracticeMode.FULL
        assert session.snapshot.story_code == "TYRES"
        assert session.snapshot.seed == session.snapshot.questions[0].scenario_seed
        assert session.prompt_message_id is not None
        assert session.control_message_id == session.prompt_message_id
        assert sum(call.__api_method__ == "sendPhoto" for call in transport.calls) == 2
        assert not any(call.__api_method__ == "sendDocument" for call in transport.calls)

        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        before = await scenario_repository.resume_session(user_id)
        assert before is not None
        # Hint callback is idempotent and leaves the independent attempt counter alone.
        assert "попыток" not in (controls.text or "")
        await callback(controls, "📷 Схема / данные")
        assert sum(call.__api_method__ == "sendPhoto" for call in transport.calls) == 4
        assert await scenario_repository.resume_session(user_id) == session
        hint_data = next(
            button.callback_data
            for row in controls.reply_markup.inline_keyboard
            for button in row
            if button.text == "💡 Подсказка"
        )
        update_id += 1
        hint_update = Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"pilot-callback-{update_id}",
                from_user=user,
                chat_instance="pilot",
                message=controls,
                data=hint_data,
            ),
        )
        await _feed(dispatcher, bot, repository, scenario_repository, hint_update)
        sends_after_hint = sum(
            call.__api_method__ in {"sendMessage", "sendPhoto", "sendDocument"}
            for call in transport.calls
        )
        await _feed(dispatcher, bot, repository, scenario_repository, hint_update)
        assert (
            sum(
                call.__api_method__ in {"sendMessage", "sendPhoto", "sendDocument"}
                for call in transport.calls
            )
            == sends_after_hint
        )
        after_hint = await scenario_repository.resume_session(user_id)
        assert after_hint is not None and after_hint.hints_used == 1
        assert after_hint.attempt_count == 0

        question = next(q for q in session.snapshot.questions if q.position == 1)
        assert after_hint.prompt_message_id is not None
        condition = next(
            item for item in transport.messages.values()
            if item.message_id == after_hint.prompt_message_id
        )
        # The answer is an ordinary message with no reply_to_message.
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=condition.message_id + 10,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text=question.canonical_answer,
                ),
            ),
        )
        solved = await scenario_repository.resume_session(user_id)
        assert solved is not None and solved.question_status == "solved"
        assert solved.attempt_count == 1
        assert_terminal_since(condition.message_id)

        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        controls = await callback(controls, "➡ Следующий вопрос")
        second = await scenario_repository.resume_session(user_id)
        assert second is not None and second.current_position == 2
        old_prompt_id = second.prompt_message_id

        controls = await callback(controls, "⏸ Пауза")
        paused = await scenario_repository.resume_session(user_id)
        assert paused is not None and paused.status == "paused"
        controls = await callback(controls, "▶ Продолжить")
        resumed = await scenario_repository.resume_session(user_id)
        assert resumed is not None and resumed.status == "active"
        assert resumed.current_position == 2 and resumed.snapshot.seed == session.snapshot.seed
        assert resumed.prompt_message_id != old_prompt_id
        assert resumed.control_message_id is not None

        # A delayed answer belonging to the prior prompt cannot affect question 2.
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=old_prompt_id + 1,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text="0",
                ),
            ),
        )
        assert (await scenario_repository.resume_session(user_id)).attempt_count == 0

        assert resumed.prompt_message_id is not None
        current_prompt = resumed.prompt_message_id
        await send("0", current_prompt + 10, reply=condition)
        assert await scenario_repository.record_attempt(
            telegram_user_id=user_id,
            session_id=resumed.session_id,
            position=2,
            telegram_message_id=current_prompt + 11,
            reply_to_message_id=condition.message_id,
            raw_answer="0",
            normalized_answer="0",
            is_correct=False,
        ) is AttemptResult.STALE

        for offset, invalid in enumerate(("не число", "12/", "1,2.3", "---", "1/0"), 12):
            await send(invalid, current_prompt + offset)
        assert (await scenario_repository.resume_session(user_id)).attempt_count == 0
        assert await oge15_navigation_pool.fetchval(
            "SELECT count(*) FROM oge15_attempts WHERE session_id=$1 AND position=2",
            resumed.session_id,
        ) == 0

        # The general Continue button follows the last selected independent training.
        await send(router.TASK6_LABEL, current_prompt + 30)
        classic = await repository.task6_state(user_id)
        assert classic is not None and classic["problem"] is not None
        paused_for_classic = await scenario_repository.resume_session(user_id, resumed.session_id)
        assert paused_for_classic is not None and paused_for_classic.status == "paused"
        await send("▶ Продолжить", current_prompt + 31)
        assert await repository.user_state(user_id) == "task6"
        assert (await repository.task6_state(user_id))["problem"] == classic["problem"]
        assert (
            await scenario_repository.resume_session(user_id, resumed.session_id)
            == paused_for_classic
        )

        # Old scenario controls are inert while №6 is the user's selected training.
        await callback(controls, "⏸ Пауза")
        assert (
            await scenario_repository.resume_session(user_id, resumed.session_id)
            == paused_for_classic
        )
        await send("/oge15", current_prompt + 32)
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await callback(menu, "Шины")
        await callback(menu, "▶ Продолжить · пятёрка · №2")
        assert await repository.user_state(user_id) == "oge15"
        assert (await repository.task6_state(user_id))["problem"] == classic["problem"]
        current_prompt = (await scenario_repository.resume_session(user_id)).prompt_message_id
        for attempt_offset in (40, 41):
            update_id += 1
            await _feed(
                dispatcher,
                bot,
                repository,
                scenario_repository,
                Update(
                    update_id=update_id,
                    message=Message(
                        message_id=current_prompt + attempt_offset,
                        date=datetime.now(UTC),
                        chat=Chat(id=user_id, type="private"),
                        from_user=user,
                        text="0",
                    ),
                ),
            )
        failed = await scenario_repository.resume_session(user_id)
        assert failed is not None and failed.question_status == "failed"
        assert failed.attempt_count == 2
        assert_terminal_since(failed.prompt_message_id)

        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        controls = await callback(controls, "➡ Следующий вопрос")
        assert (await scenario_repository.resume_session(user_id)).current_position == 3
        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        active_controls_id = controls.message_id
        controls = await callback(controls, "📘 Разбор")
        assert_terminal_since(active_controls_id)
        terminal = await scenario_repository.resume_session(user_id)
        assert terminal is not None and terminal.question_status == "solution_viewed"
        controls = await callback(controls, "➡ Следующий вопрос")
        for expected_position in (4, 5):
            controls = max(
                (item for item in transport.messages.values() if item.reply_markup is not None),
                key=lambda item: item.message_id,
            )
            active = await scenario_repository.resume_session(user_id)
            assert active is not None and active.current_position == expected_position
            controls = await callback(controls, "⏭ Пропустить")
        assert await scenario_repository.resume_session(user_id) is None
        recent = await scenario_repository.recent_questions(user_id)
        assert len(recent) == 5
        assert {family for family, _, _ in recent} == {
            question.family_id for question in session.snapshot.questions
        }
        stats = await scenario_repository.position_stats(user_id)
        assert stats[0]["issued"] == 5
        assert stats[0]["correct"] == 1
        assert stats[0]["skipped"] == 2
        assert stats[0]["solutions_viewed"] == 1

        # Another user can open the public menu but cannot change the first user's session.
        outsider_id = user_id + 1
        outsider = User(id=outsider_id, is_bot=False, first_name="Outsider")
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"outsider-{update_id}",
                    from_user=outsider,
                    chat_instance="pilot",
                    message=controls,
                    data="oge15:home",
                ),
            ),
        )
        assert await scenario_repository.resume_session(user_id) is None

        # Single mode selects exactly one saved-snapshot position and completes
        # independently from the previous full session.
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=900,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text="/oge15",
                ),
            ),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await callback(menu, "Бумага")
        menu = await callback(menu, "Одно задание")
        menu = await callback(menu, "№3")
        single = await scenario_repository.resume_session(user_id)
        assert single is not None and single.mode is PracticeMode.SINGLE
        assert single.current_position == 3
        selected = next(q for q in single.snapshot.questions if q.position == 3)
        update_id += 1
        await _feed(
            dispatcher,
            bot,
            repository,
            scenario_repository,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=1000,
                    date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"),
                    from_user=user,
                    text=selected.canonical_answer,
                ),
            ),
        )
        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        await callback(controls, "Завершить")
        assert await scenario_repository.resume_session(user_id) is None
    finally:
        await bot.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("story_code", (*scenario_training.STORY_NAMES, "RANDOM"))
async def test_dispatcher_public_menu_navigation_opens_real_oge15_task(
    oge15_navigation_pool, story_code, monkeypatch,

) -> None:
    baseline = os.getenv("OGE15_BASELINE_MEASUREMENT") == "1"
    monkeypatch.setattr(scenario_training.secrets, "randbelow", lambda _: 42)
    transport = TelegramSession()
    bot = Bot("123456:TEST", session=transport)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    repository = PostgresRepository(oge15_navigation_pool)
    scenario_repository = ScenarioPostgresRepository(oge15_navigation_pool)
    user_id = int(uuid4().int % (2**62)) + 1
    user = User(id=user_id, is_bot=False, first_name="Menu regression")
    await repository.register_user(user_id)
    await repository.save_user_state(user_id, "main_menu")
    update_id = 1

    async def tap(message: Message, label: str, *, repeat: bool = False) -> Message:
        nonlocal update_id
        data = next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if button.text == label
        )
        update_id += 1
        update = Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"public-nav-{update_id}",
                from_user=user,
                chat_instance="public-nav",
                message=message,
                data=data,
            ),
        )
        await _feed(dispatcher, bot, repository, scenario_repository, update)
        if repeat:
            update_id += 1
            await _feed(
                dispatcher, bot, repository, scenario_repository,
                update.model_copy(update={"update_id": update_id}),
            )
        return max(transport.messages.values(), key=lambda item: item.message_id)

    try:
        await _feed(
            dispatcher, bot, repository, scenario_repository,
            Update(update_id=update_id, message=Message(
                message_id=10, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/start",
            )),
        )
        main = max(transport.messages.values(), key=lambda item: item.message_id)
        number_menu = await tap(main, "🧮 По номеру")
        oge15_button = next(
            button for row in number_menu.reply_markup.inline_keyboard
            for button in row if button.text == "№1–5 · Практические задания"
        )
        assert oge15_button.callback_data is not None
        assert oge15_button.callback_data.startswith("nav:oge15~")
        selection = await tap(number_menu, "№1–5 · Практические задания", repeat=True)
        assert any(
            "Выберите сюжет" in (message.text or "")
            for message in transport.messages.values()
        )
        label = "🎲 Случайный сюжет" if story_code == "RANDOM" else (
            scenario_training.STORY_NAMES[story_code]
        )
        story = await tap(selection, label)
        mode = await tap(story, "Вся пятёрка")
        session = await scenario_repository.resume_session(user_id)
        assert session is not None
        if story_code == "RANDOM":
            assert session.snapshot.story_code in scenario_training.STORY_NAMES
        else:
            assert session.snapshot.story_code == story_code
        assert session.mode is PracticeMode.FULL
        assert any(
            "Задание №1 из 5" in (message.text or "")
            for message in transport.messages.values()
        )

        for position, question in enumerate(session.snapshot.questions, 1):
            active = await scenario_repository.resume_session(user_id)
            assert active is not None and active.current_position == position
            if baseline:
                assert active.control_message_id == mode.message_id
            else:
                assert active.prompt_message_id == mode.message_id
                assert "попыток" not in (mode.text or "")
            update_id += 1
            await _feed(
                dispatcher, bot, repository, scenario_repository,
                Update(update_id=update_id, message=Message(
                    message_id=10000 + update_id, date=datetime.now(UTC),
                    chat=Chat(id=user_id, type="private"), from_user=user,
                    text=question.canonical_answer,
                )),
            )
            outcome = await scenario_repository.resume_session(user_id)
            assert outcome is not None and outcome.question_status == "solved"
            result = transport.messages[outcome.control_message_id]
            if baseline:
                assert any(message.text == "Верно!" for message in transport.messages.values())
            else:
                assert "Ответ засчитан" in (result.text or "")
            mode = await tap(result, "➡ Следующий вопрос" if position < 5 else "Завершить")
        assert await scenario_repository.resume_session(user_id) is None
        assert (await scenario_repository.position_stats(user_id))[0]["correct"] == 5
        assert not any(call.__api_method__ == "sendDocument" for call in transport.calls)

        counts = Counter(call.__api_method__ for call in transport.calls)
        variant = "main-before-V2" if baseline else "V2"
        print(f"OGE15 full pass {variant} {story_code}: {dict(sorted(counts.items()))}")

        # The command remains a public entry point and can be used after returning.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, scenario_repository,
            Update(update_id=update_id, message=Message(
                message_id=11, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        assert any(
            "Выберите сюжет" in (message.text or "")
            for message in transport.messages.values()
        )
        assert mode.message_id > 0
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_dispatcher_switches_full_sessions_without_losing_progress(oge15_navigation_pool):
    transport = TelegramSession()
    bot = Bot("123456:TEST", session=transport)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    repository = PostgresRepository(oge15_navigation_pool)
    store = ScenarioPostgresRepository(oge15_navigation_pool)
    user_id = int(uuid4().int % (2**62)) + 1
    user = User(id=user_id, is_bot=False, first_name="Switch sessions")
    await repository.register_user(user_id)
    await repository.save_user_state(user_id, "main_menu")
    update_id = 1
    user_message_id = 50000

    async def tap(message: Message, label: str) -> Message:
        nonlocal update_id
        data = next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if button.text == label
        )
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, callback_query=CallbackQuery(
                id=f"switch-{update_id}", from_user=user, chat_instance="switch",
                message=message, data=data,
            )),
        )
        return max(transport.messages.values(), key=lambda item: item.message_id)

    async def send_answer(answer: str, *, reply: Message | None = None) -> None:
        nonlocal update_id, user_message_id
        update_id += 1
        user_message_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=user_message_id, date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"), from_user=user, text=answer,
                reply_to_message=reply,
            )),
        )

    def latest_control(session: ScenarioSession) -> Message:
        session_id = session.control_message_id
        assert session_id is not None
        return transport.messages[session_id]

    try:
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=1, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Шины")
        menu = await tap(menu, "Вся пятёрка")
        tyres = await store.resume_session(user_id)
        assert tyres is not None and tyres.snapshot.story_code == "TYRES"
        old_prompt = transport.messages[tyres.prompt_message_id]

        # Solve the first two TYRES questions and leave the saved session on #3.
        for expected_position in (1, 2):
            active = await store.resume_session(user_id)
            assert active is not None and active.current_position == expected_position
            question = active.snapshot.questions[expected_position - 1]
            await send_answer(question.canonical_answer)
            solved = await store.resume_session(user_id)
            assert solved is not None and solved.question_status == "solved"
            await tap(latest_control(solved), "➡ Следующий вопрос")
        tyres = await store.find_open_session(user_id, "TYRES", PracticeMode.FULL)
        assert tyres is not None and tyres.current_position == 3
        old_controls = latest_control(tyres)

        # Starting PAPER atomically pauses TYRES. Delayed controls/replies remain stale.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=2, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Бумага")
        menu = await tap(menu, "Вся пятёрка")
        paper = await store.resume_session(user_id)
        assert paper is not None and paper.snapshot.story_code == "PAPER"
        assert (await store.resume_session(user_id, tyres.session_id)).status == "paused"
        paper_before_stale = paper
        await tap(old_controls, "💡 Подсказка")
        assert await store.resume_session(user_id) == paper_before_stale
        await send_answer("1", reply=old_prompt)
        assert await store.resume_session(user_id) == paper_before_stale
        assert await oge15_navigation_pool.fetchval(
            "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", paper.session_id
        ) == 0

        for expected_position in (1, 2, 3):
            active = await store.resume_session(user_id)
            assert active is not None and active.current_position == expected_position
            question = active.snapshot.questions[expected_position - 1]
            await send_answer(question.canonical_answer)
            solved = await store.resume_session(user_id)
            assert solved is not None and solved.question_status == "solved"
            await tap(latest_control(solved), "➡ Следующий вопрос")
        paper = await store.find_open_session(user_id, "PAPER", PracticeMode.FULL)
        assert paper is not None and paper.current_position == 4

        # Choosing TYRES offers the exact saved session; it resumes at question #3.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=3, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Шины")
        menu = await tap(menu, "▶ Продолжить · пятёрка · №3")
        resumed_tyres = await store.resume_session(user_id)
        assert resumed_tyres is not None and resumed_tyres.session_id == tyres.session_id
        assert resumed_tyres.current_position == 3
        assert resumed_tyres.snapshot.seed == tyres.snapshot.seed
        assert (await store.resume_session(user_id, paper.session_id)).status == "paused"
        superseded_controls = latest_control(resumed_tyres)

        # /start exposes Continue, which returns to the most recently used saved workout.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=4, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/start",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        assert any(
            button.text == "▶ Продолжить"
            for row in menu.reply_markup.inline_keyboard for button in row
        )
        menu = await tap(menu, "▶ Продолжить")
        after_continue = await store.resume_session(user_id)
        assert after_continue is not None and after_continue.session_id == tyres.session_id
        await tap(superseded_controls, "💡 Подсказка")
        assert await store.resume_session(user_id) == after_continue

        # Switch from the saved full set to an ordinary number, then return to
        # the exact TYRES snapshot/position through global Continue.
        async def direct_message(text: str) -> AsyncMock:
            nonlocal user_message_id
            user_message_id += 2
            message = AsyncMock()
            message.from_user = user
            message.text = text
            message.message_id = user_message_id
            message.answer.return_value = SimpleNamespace(message_id=user_message_id + 1)
            return message

        await choose_task12(await direct_message("№12 · Формулы"), repository, store)
        task12_before = await repository.task12_state(user_id)
        assert task12_before is not None and isinstance(task12_before["problem"], dict)
        task12_problem_id = str(task12_before["problem"]["problem_id"])
        await return_to_menu(await direct_message("↩ В меню"), repository, store)
        restarted = PostgresRepository(oge15_navigation_pool)
        await continue_session(await direct_message("▶ Продолжить"), restarted, store)
        task12_after = await restarted.task12_state(user_id)
        assert task12_after is not None
        assert task12_after["problem"]["problem_id"] == task12_problem_id
        assert task12_after["state"]["status"] == "active"

        # Choosing the saved OGE15 context makes it last-used again. Global
        # Continue restores the same persisted session without resetting it.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=7, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Шины")
        await tap(menu, "▶ Продолжить · пятёрка · №3")
        selected_tyres = await store.resume_session(user_id)
        assert selected_tyres is not None
        assert selected_tyres.session_id == tyres.session_id
        assert selected_tyres.snapshot.seed == tyres.snapshot.seed
        await return_to_menu(await direct_message("↩ В меню"), restarted, store)
        await continue_session(await direct_message("▶ Продолжить"), restarted, store)
        continued_tyres = await store.resume_session(user_id)
        assert continued_tyres is not None
        assert continued_tyres.session_id == tyres.session_id
        assert continued_tyres.current_position == 3
        assert continued_tyres.snapshot.seed == tyres.snapshot.seed
        assert (await restarted.task12_state(user_id))["problem"]["problem_id"] == task12_problem_id

        # Continue the saved PAPER run and finish early; pending positions are not skipped.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=8, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Бумага")
        await tap(menu, "▶ Продолжить · пятёрка · №4")
        paper = await store.resume_session(user_id)
        assert paper is not None and paper.current_position == 4
        controls = latest_control(paper)
        assert any(
            button.text == "⏹ Завершить тренировку"
            for row in controls.reply_markup.inline_keyboard for button in row
        )
        await tap(controls, "⏹ Завершить тренировку")
        terminal_card = transport.messages[controls.message_id]
        assert "Напишите ответ" not in (terminal_card.text or "")
        assert terminal_card.reply_markup is None
        assert await store.resume_session(user_id, paper.session_id) is None
        paper_stats = await store.position_stats(user_id)
        # TYRES contributes two issued positions and PAPER three. The concurrent
        # GARDEN/FLAT starts each issue only #1. Active PAPER #4 and pending #5
        # remain unscored instead of becoming incorrect or skipped.
        assert paper_stats[0]["correct"] == 5
        assert paper_stats[0]["skipped"] == 0
        assert paper_stats[0]["issued"] == 7
        untouched = await oge15_navigation_pool.fetch(
            """SELECT position, status FROM oge15_question_progress
               WHERE session_id=$1 AND position IN (4,5) ORDER BY position""",
            paper.session_id,
        )
        assert [(row["position"], row["status"]) for row in untouched] == [
            (4, "active"), (5, "pending")
        ]
        assert await oge15_navigation_pool.fetchval(
            "SELECT count(*) FROM oge15_attempts WHERE session_id=$1 AND position IN (4,5)",
            paper.session_id,
        ) == 0

        # A SINGLE session can be started while the saved TYRES full session remains intact.
        await store.resume_paused(user_id, tyres.session_id)
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=5, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Шины")
        menu = await tap(menu, "Выбрать одно задание")
        menu = await tap(menu, "№4")
        single = await store.resume_session(user_id)
        assert single is not None and single.mode is PracticeMode.SINGLE
        assert (await store.resume_session(user_id, tyres.session_id)).status == "paused"
        assert (await store.find_open_session(
            user_id, "TYRES", PracticeMode.FULL
        )).session_id == tyres.session_id

        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=6, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "📂 Незавершённые тренировки")
        menu = await tap(menu, "▶ Шины · пятёрка · №3")
        assert (await store.resume_session(user_id)).session_id == tyres.session_id
        assert (await store.resume_session(user_id, single.session_id)).status == "paused"

        # Distinct users can atomically foreground sessions without affecting each other.
        other_id = user_id + 1
        registry = scenario_training.public_registry()
        other = await store.start_session(
            other_id,
            build_practice_plan(
                PracticeRequest(PracticeMode.FULL, 514, "PAPER"), registry
            ).snapshot,
            PracticeMode.FULL, (1, 2, 3, 4, 5),
        )
        assert other is not None
        other_tyres = await store.start_session(
            other_id,
            build_practice_plan(
                PracticeRequest(PracticeMode.FULL, 515, "TYRES"), registry
            ).snapshot,
            PracticeMode.FULL, (1, 2, 3, 4, 5),
        )
        assert other_tyres is not None
        user_resume, other_resume = await asyncio.gather(
            store.resume_paused(user_id, tyres.session_id),
            store.resume_paused(other_id, other.session_id),
        )
        assert user_resume is not None and user_resume.session_id == tyres.session_id
        assert other_resume is not None and other_resume.session_id == other.session_id
        assert (await store.resume_session(other_id, other_tyres.session_id)).status == "paused"
        assert (await store.resume_session(other_id)).session_id == other.session_id
        assert (await store.resume_session(user_id)).session_id == tyres.session_id

        # Restart is explicit: it closes only the selected full session and retains its history.
        update_id += 1
        await _feed(
            dispatcher, bot, repository, store,
            Update(update_id=update_id, message=Message(
                message_id=7, date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                from_user=user, text="/oge15",
            )),
        )
        menu = max(transport.messages.values(), key=lambda item: item.message_id)
        menu = await tap(menu, "Шины")
        await tap(menu, "🆕 Начать заново · пятёрка")
        restarted_tyres = await store.resume_session(user_id)
        assert restarted_tyres is not None
        assert restarted_tyres.session_id != tyres.session_id
        assert restarted_tyres.current_position == 1
        assert await store.resume_session(user_id, tyres.session_id) is None
        assert await oge15_navigation_pool.fetchval(
            "SELECT count(*) FROM oge15_attempts WHERE session_id=$1", tyres.session_id
        ) == 2
        # Switching the first user's session must not pause the second user's foreground run.
        assert (await store.resume_session(other_id, other.session_id)).status == "active"
    finally:
        await oge15_navigation_pool.execute(
            "DELETE FROM users WHERE telegram_user_id=ANY($1::bigint[])", [user_id, user_id + 1]
        )
        await bot.session.close()


@pytest.mark.asyncio
async def test_legacy_paper_retires_only_session_with_unfinished_exposed_question(
    oge15_navigation_pool,
):
    store = ScenarioPostgresRepository(oge15_navigation_pool)
    user_id = int(uuid4().int % (2**62)) + 1
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 42, "PAPER"), scenario_training.public_registry()
    ).snapshot
    legacy = replace(snapshot, generator_version="paper-v1")
    safe = await store.start_session(user_id, legacy, PracticeMode.SINGLE, (2,))
    assert not await store.close_legacy_with_exposed_answer(user_id, safe)
    other_user = user_id + 1
    exposed = await store.start_session(other_user, legacy, PracticeMode.SINGLE, (1,))
    assert not await store.close_legacy_with_exposed_answer(user_id, exposed)
    before = await store.position_stats(other_user)
    assert await store.close_legacy_with_exposed_answer(other_user, exposed)
    assert await store.resume_session(other_user) is None
    assert await store.resume_session(user_id) == safe
    assert await store.position_stats(other_user) == before


@pytest.mark.asyncio
async def test_concurrent_scenario_callbacks_and_replies_are_user_scoped(oge15_navigation_pool):
    transport = TelegramSession()
    bot = Bot("123456:TEST", session=transport)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    repository = PostgresRepository(oge15_navigation_pool)
    store = ScenarioPostgresRepository(oge15_navigation_pool)
    base = int(uuid4().int % (2**62)) + 1
    users = [User(id=base + i, is_bot=False, first_name=f"Student {i}") for i in range(2)]
    cards = []
    answers = []

    def incoming(user: User, message_id: int, **fields) -> Message:
        return Message(
            message_id=message_id, date=datetime.now(UTC),
            chat=Chat(id=user.id, type="private"), from_user=user, **fields,
        ).as_(bot)

    async def dispatch(update: Update) -> None:
        await _feed(dispatcher, bot, repository, store, update)

    def hint(user: User, card: Message, update_id: int) -> Update:
        button = next(button for row in card.reply_markup.inline_keyboard for button in row
                      if button.text == "💡 Подсказка")
        return Update(update_id=update_id, callback_query=CallbackQuery(
            id=f"concurrent-{update_id}", from_user=user, chat_instance=str(user.id),
            message=card, data=button.callback_data,
        ))

    try:
        for i, (user, story) in enumerate(zip(users, ("TYRES", "GARDEN"), strict=True)):
            plan = build_practice_plan(
                PracticeRequest(PracticeMode.SINGLE, 42, story, 1),
                scenario_training.public_registry(),
            )
            session = await store.start_session(user.id, plan.snapshot, plan.mode, (1,))
            await repository.save_user_state(user.id, "oge15")
            await scenario_training.render_session(
                incoming(user, i + 1), store, session, show_assets=True,
            )
            current = await store.resume_session(user.id)
            assert current is not None
            cards.append(transport.messages[current.control_message_id])
            answers.append(plan.snapshot.questions[0].canonical_answer)

        # Crossed callbacks and Replies interleave with a legitimate hint for each user.
        await asyncio.gather(
            dispatch(hint(users[0], cards[1], 101)),
            dispatch(hint(users[1], cards[0], 102)),
            dispatch(hint(users[0], cards[0], 103)),
            dispatch(hint(users[1], cards[1], 104)),
            *(
                dispatch(Update(update_id=110 + i, message=incoming(
                    user, 10000 + i, text=answers[i], reply_to_message=cards[1 - i],
                )))
                for i, user in enumerate(users)
            ),
        )
        current_cards = []
        for user in users:
            current = await store.resume_session(user.id)
            assert current is not None and current.attempt_count == 0 and current.hints_used == 1
            current_cards.append(transport.messages[current.prompt_message_id])

        await asyncio.gather(*(
            dispatch(Update(update_id=120 + i, message=incoming(
                user, 11000 + i, text=answers[i], reply_to_message=current_cards[i],
            )))
            for i, user in enumerate(users)
        ))
        for user in users:
            current = await store.resume_session(user.id)
            assert current is not None and current.question_status == "solved"
            assert current.attempt_count == 1 and current.hints_used == 1
    finally:
        await bot.session.close()
