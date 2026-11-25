from datetime import UTC, datetime

from app.adaptive.engine import Stage, State
from app.bot import adaptive, menu


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_training_hub_offers_exactly_four_directions_and_contextual_resume():
    callbacks = _callbacks(menu.trainings_hub())
    assert callbacks == [
        "train:personal",
        "train:areas",
        "train:mixed",
        "nav:mixed",
        "nav:main",
    ]
    assert "train:personal" not in _callbacks(menu.trainings_hub(personal_enabled=False))
    assert _callbacks(menu.trainings_hub(has_session=True)) == ["nav:resume", *callbacks]


def test_short_training_result_offers_similar_and_next():
    row = {
        "problem": "00000000-0000-0000-0000-000000000001",
        "id": "00000000-0000-0000-0000-000000000002",
        "position": 0,
        "outcome": "solved",
    }
    callbacks = _callbacks(adaptive.keyboard(row))
    assert callbacks[:2] == [
        "ad:similar:00000000-0000-0000-0000-000000000001",
        "ad:next:00000000-0000-0000-0000-000000000001",
    ]


def test_all_short_mode_plans_have_five_positions():
    choices = adaptive.catalog()
    family, number = next(iter(choices.items()))
    history = [(number, family, State(stage=Stage.GAP, opened=1), datetime.now(UTC))]
    assert len(adaptive._mode_plan("personal", 42, history, {})) == 5
    assert len(adaptive._mode_plan("mixed", 42, history, {})) == 5
    assert len(adaptive._mode_plan("number", 42, history, {}, number=number)) == 5
    assert adaptive._mode_plan("family", 42, history, {}, family=family) == [family] * 5


def test_area_filters_use_public_names_and_deep_link_route():
    _, number = next(iter(adaptive.catalog().items()))
    callbacks = _callbacks(adaptive.family_area_keyboard(number))
    assert f"train:number:{number}" in callbacks
    assert any(callback.startswith("train:family:") for callback in callbacks)
    assert all(len(callback.encode()) <= 64 for callback in callbacks)
    longest = max(adaptive.catalog(), key=lambda value: len(value.encode()))
    switch = adaptive._switch_callback("family", None, longest) + "~" + "a" * 12
    assert len(switch.encode()) <= 64
    grid = adaptive.area_keyboard().inline_keyboard
    assert grid[0][0].text == "№1–5 · Связанный сюжет"
    assert grid[0][0].callback_data == "nav:linked"
    assert {button.callback_data for row in grid[1:-1] for button in row} == {
        f"train:area:{n}" for n in range(1, 20)
    }


def test_unified_area_preserves_existing_written_menu_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from app.bot.navigation import navigation_screen

    settings = SimpleNamespace(oge_part2_enabled=True)
    monkeypatch.setattr(adaptive, "get_settings", lambda: settings)
    keyboard = adaptive.area_keyboard()
    assert {c for c in _callbacks(keyboard) if c.startswith("p2:")} == {
        f"p2:menu:{n}" for n in range(20, 26)
    }
    assert navigation_screen(keyboard) == "trainings"


async def test_companion_transport_short_training_hub_and_completion(bank_pool, monkeypatch):
    import json
    import os
    from uuid import uuid4

    import asyncpg
    from test_companion_qa import Harness, config

    from app.adaptive.session import Session
    from app.bot.mixed_training import _is_correct
    from app.companion.storage import open_storage
    from app.persistence.scenario_repository import ScenarioPostgresRepository

    # Use public numeric families with a valid wrong answer and fresh analogues.
    choices = {family: n for family, n in adaptive.catalog().items() if n in {6, 8, 9}}
    monkeypatch.setattr(adaptive, "catalog", lambda: choices)
    url = os.environ["DATABASE_URL"]
    repo = await open_storage(url, 300_000_000 + int(uuid4().hex[:7], 16))
    harness = Harness(
        repo,
        config(oge_companion_adaptive_enabled=True),
        ScenarioPostgresRepository(repo._pool),
    )
    try:
        await harness.message("/start")
        await harness.click("exit")
        await harness.click("nav:trainings")
        assert "Тренировки" in harness.text()
        await harness.click("train:personal")
        session = Session(repo, 42)
        row = await session.current()
        assert row and row["position"] == 0 and row["problem"]

        problem = adaptive.problem_data(row)
        wrong = next(
            candidate
            for candidate in (
                "0", "1", "2", "3", "4", "123", "132", "213", "231", "312", "321",
            )
            if _is_correct(problem["number"], problem, candidate) is False
        )
        await harness.message(wrong)
        assert "Попробуй ещё раз" in harness.text()
        await harness.message(wrong)
        assert "Разбор:" in harness.text()
        await harness.click(f"ad:similar:{row['problem']}")
        current = await session.current()
        assert current and current["position"] == 1
        assert json.loads(current["plan"])[1] == json.loads(row["plan"])[0]

        while current is not None:
            if current["outcome"] == "issued":
                await harness.click(f"ad:skip:{current['problem']}")
                current = await session.current()
                if current is None:
                    break
            await harness.click(f"ad:next:{current['problem']}")
            current = await session.current()

        transcript = harness.text()
        assert "Тренировка завершена" in transcript
        assert "Решено верно: 0 из 5" in transcript
        assert "Что потренировать дальше" in transcript
        await harness.click("train:progress")
        assert await repo.user_state(42) == "progress"
        print(transcript)
    finally:
        await harness.bot.session.close()
        schema = repo.schema
        await repo._pool.close()
        connection = await asyncpg.connect(url)
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


async def test_generation_failure_leaves_retriable_session_and_no_empty_summary(
    bank_pool, monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.adaptive.session import Session
    from app.math.scenarios.recent_questions import ScenarioVariantSearchFailed
    from app.persistence.repository import PostgresRepository

    family = "STOVE-F04-FLOOR-AREA"
    repository = PostgresRepository(bank_pool)
    store = Session(repository, 1)
    await store.start([family] * 5, strategy="family", scope={"family": family})
    settings = SimpleNamespace(oge_adaptive_enabled=True)
    monkeypatch.setattr(adaptive, "get_settings", lambda: settings)
    real_generate = adaptive.generate

    def fail(*_):
        raise ScenarioVariantSearchFailed(family)

    monkeypatch.setattr(adaptive, "generate", fail)
    sent = AsyncMock(return_value=SimpleNamespace(message_id=12))
    monkeypatch.setattr(adaptive, "send_text", sent)
    await adaptive.present(object(), repository, 1)
    row = await store.current()
    assert row["problem"] is None and row["prompt"] == 12
    assert sent.await_args.args[2] == "Не получилось подготовить задачу. Попробуй ещё раз."
    assert not any(
        button.startswith("ad:repeat")
        for button in _callbacks(sent.await_args.kwargs["reply_markup"])
    )

    monkeypatch.setattr(adaptive, "generate", real_generate)
    problem_sent = AsyncMock()
    monkeypatch.setattr(adaptive, "_send_problem", problem_sent)
    await adaptive.present(object(), repository, 1, expected_prompt=11)  # Stale retry.
    assert not problem_sent.await_count
    await adaptive.present(object(), repository, 1, expected_prompt=12)
    assert problem_sent.await_count == 1
    current = await store.current()
    assert current["id"] == row["id"] and current["position"] == 0 and current["problem"]


async def test_disabled_personal_switch_and_progress_family_conflict(bank_pool):
    import json
    import os
    from uuid import uuid4

    import asyncpg
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from test_companion_qa import Harness, config

    from app.adaptive.session import Session
    from app.bot.presentation import send_text
    from app.companion.storage import open_storage
    from app.persistence.scenario_repository import ScenarioPostgresRepository

    url = os.environ["DATABASE_URL"]
    repo = await open_storage(url, 400_000_000 + int(uuid4().hex[:7], 16))
    harness = Harness(
        repo,
        config(oge_companion_adaptive_enabled=True),
        ScenarioPostgresRepository(repo._pool),
    )
    try:
        await harness.message("/start")
        await harness.click("exit")
        await harness.click("nav:trainings")
        await repo._pool.execute(
            """UPDATE users SET current_state=current_state ||
            '{"resume_mode":"task6"}'::jsonb WHERE telegram_user_id=42"""
        )
        await harness.click("train:personal")
        session = Session(repo, 42)
        personal = await session.current()
        assert personal and personal["strategy"] == "personal"
        await harness.click(f"ad:menu:{personal['problem']}")
        await repo.set_personal_enabled(42, False)
        await harness.click("nav:trainings")
        disabled_hub, _ = harness.button("train:mixed")
        assert "Рекомендую:" not in (disabled_hub.text or "")
        assert all(
            callback.partition("~")[0] != "train:personal"
            for callback in _callbacks(disabled_hub.reply_markup)
        )
        await harness.click("train:mixed")
        switch_message, _ = harness.button("train:x:m")
        callbacks = [
            button.callback_data.partition("~")[0]
            for row in switch_message.reply_markup.inline_keyboard
            for button in row
        ]
        assert "train:resume" not in callbacks
        assert await repo.user_state(42) == "trainings"
        await harness.click("train:x:m")
        mixed = await session.current()
        assert mixed and mixed["strategy"] == "mixed" and mixed["id"] != personal["id"]
        mixed_scope = mixed["scope"]
        if isinstance(mixed_scope, str):
            mixed_scope = json.loads(mixed_scope)
        assert mixed_scope["resume_fallback"] == "task6"
        early_summary, _ = harness.button("train:mixed")
        early_callbacks = [
            button.callback_data.partition("~")[0]
            for row in early_summary.reply_markup.inline_keyboard
            for button in row
        ]
        assert "train:personal" not in early_callbacks
        assert "Рекомендую:" not in (early_summary.text or "")

        family = next(iter(adaptive.catalog()))
        await repo.save_user_state(42, "progress")
        source = next(reversed(harness.transport.messages.values()))
        await send_text(
            source,
            repo,
            "Прогресс по типу",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Тренировать", callback_data=f"train:family:{family}"
                )],
                [InlineKeyboardButton(text="К прогрессу", callback_data="nav:progress")],
            ]),
            user_id_override=42,
        )
        await harness.click(f"train:family:{family}")
        assert await repo.user_state(42) == "trainings"
        await harness.click("train:hub")
        assert "Тренировки" in harness.text()
    finally:
        await harness.bot.session.close()
        schema = repo.schema
        await repo._pool.close()
        connection = await asyncpg.connect(url)
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()
