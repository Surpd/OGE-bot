from datetime import UTC, datetime

from app.adaptive.engine import Stage, State
from app.bot import adaptive, menu


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_training_hub_keeps_short_and_existing_modes_distinct():
    callbacks = _callbacks(menu.trainings_hub())
    assert callbacks == [
        "train:personal",
        "train:areas",
        "train:mixed",
        "nav:numbers",
        "nav:mixed",
        "nav:main",
    ]
    assert "train:personal" not in _callbacks(menu.trainings_hub(personal_enabled=False))


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
    assert len(adaptive._mode_plan("personal", history)) == 5
    assert len(adaptive._mode_plan("mixed", history)) == 5
    assert len(adaptive._mode_plan("number", history, number=number)) == 5
    assert adaptive._mode_plan("family", history, family=family) == [family] * 5


def test_area_filters_use_public_names_and_deep_link_route():
    _, number = next(iter(adaptive.catalog().items()))
    callbacks = _callbacks(adaptive.family_area_keyboard(number))
    assert f"train:number:{number}" in callbacks
    assert any(callback.startswith("train:family:") for callback in callbacks)
    assert all(len(callback.encode()) <= 64 for callback in callbacks)
    longest = max(adaptive.catalog(), key=lambda value: len(value.encode()))
    switch = adaptive._switch_callback("family", None, longest) + "~" + "a" * 12
    assert len(switch.encode()) <= 64


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

    # Stable family selection, while fingerprints and navigation revisions remain fresh.
    token_hex = adaptive.secrets.token_hex
    monkeypatch.setattr(
        adaptive.secrets, "token_hex", lambda size: "73" if size == 8 else token_hex(size)
    )
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
        assert "Короткая тренировка — 5 задач" in harness.text()
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
        assert "Пока неверно" in harness.text()
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
        assert "Пройдено задач: 5" in transcript
        assert "Что дальше" in transcript
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
