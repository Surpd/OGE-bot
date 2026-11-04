from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_inline_dispatcher_postgres import TelegramSession
from test_navigation_postgres import navigation_pool as postgres_db_fixture  # noqa: F401, F811

from app.bot import router, scenario_training
from app.bot.router import build_router
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    restore_asset_bytes,
)
from app.persistence.repository import PostgresRepository
from app.persistence.scenario_repository import AttemptResult, ScenarioPostgresRepository


@pytest.fixture
async def oge15_navigation_pool(postgres_db_fixture):  # noqa: F811
    return postgres_db_fixture



def test_oge15_public_number_menu_and_story_exclusions() -> None:
    from app.bot.menu import number_menu

    buttons = [b for row in number_menu().inline_keyboard for b in row]
    assert any(
        b.text == "№1–5 · Практические задания" and b.callback_data == "oge15:home"
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
        assert session.control_message_id is not None

        controls = max(
            (item for item in transport.messages.values() if item.reply_markup is not None),
            key=lambda item: item.message_id,
        )
        before = await scenario_repository.resume_session(user_id)
        assert before is not None
        # Hint callback is idempotent and leaves the independent attempt counter alone.
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
        await send("▶ Продолжить", current_prompt + 31)
        assert await repository.user_state(user_id) == "task6"
        assert (await repository.task6_state(user_id))["problem"] == classic["problem"]
        assert await scenario_repository.resume_session(user_id) == resumed

        await callback(controls, "⏸ Пауза")
        pause_message = max(transport.messages.values(), key=lambda item: item.message_id)
        await callback(pause_message, "▶ Продолжить")
        await send("▶ Продолжить", current_prompt + 32)
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
