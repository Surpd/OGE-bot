from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.math.oge17_generator import generate
from app.math.oge17_models import ENABLED_FAMILIES, FAMILIES
from app.math.oge17_scheduler import build_task17_candidate_batch
from app.persistence.repository import MemoryRepository


@pytest.fixture(autouse=True)
def implemented_families_for_test(monkeypatch):
    from app.math import oge17_models, oge17_scheduler

    monkeypatch.setattr(oge17_models, "ENABLED_FAMILIES", FAMILIES)
    monkeypatch.setattr(oge17_scheduler, "ENABLED_FAMILIES", FAMILIES)


def test_task17_recent_repeat_queue_covers_enabled_families():
    assert ENABLED_FAMILIES == FAMILIES
    state: dict[str, object] = {}
    issued: set[str] = set()
    families: set[str] = set()
    for seed in range(36):
        candidate = build_task17_candidate_batch(state, seed)[0]
        assert candidate["fingerprint"] not in issued
        issued.add(str(candidate["fingerprint"]))
        families.add(str(candidate["family_id"]))
        state["last_family_id"] = candidate["_last_family_after"]
        state["family_queue"] = candidate["_family_queue_after"]
        recent = list(issued)[-30:]
        state["recent_fingerprints"] = recent
    assert families == set(FAMILIES)


def test_task17_webhook_answer_records_once_and_resume_preserves_snapshot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "task17-test-secret")
    get_settings.cache_clear()
    repository = MemoryRepository()
    snapshot = generate("OGE17-E03", 55).to_snapshot()

    async def prepare() -> None:
        await repository.ensure_task17_session(42)
        await repository.advance_task17_problem(42, None, [snapshot])
        await repository.save_user_state(42, "task17")
        await repository.set_task17_condition_message(42, snapshot["problem_id"], 100)

    asyncio.run(prepare())
    bot = Bot("123456:TEST")
    sent = Message(message_id=102, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.session.make_request = AsyncMock(return_value=sent)
    app = create_app(repository=repository, bot=bot, run_schema_migrations=False)
    payload = {
        "update_id": 17001,
        "message": {
            "message_id": 101,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Student"},
            "text": snapshot["correct_answer"],
        },
    }
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "task17-test-secret"},
            )
            assert response.status_code == 200
    state = asyncio.run(repository.task17_state(42))
    assert state is not None and state["problem"]["problem_id"] == snapshot["problem_id"]
    assert asyncio.run(repository.task17_progress(42))["correct"] == 1
    assert len(repository.attempts17[42]) == 1


def test_task17_choice_is_available_with_no_fingerprint_threshold():
    from app.bot.family_selection import family_keyboard
    from app.bot.trainings import BY_NUMBER

    assert BY_NUMBER[17].available
    keyboard = family_keyboard(17)
    assert len(keyboard.inline_keyboard) == len(FAMILIES) + 2
    assert keyboard.inline_keyboard[0][0].callback_data == "nav:family:17:random"
