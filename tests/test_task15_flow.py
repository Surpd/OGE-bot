from datetime import UTC, datetime
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.types import Chat, Message

from app.math import oge15_scheduler
from app.math.oge15_triangles import FAMILIES, generate
from app.persistence.repository import MemoryRepository


def test_task15_duplicate_webhook_is_processed_once(monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "oge15-test-secret")
    monkeypatch.setattr(oge15_scheduler, "ENABLED_FAMILIES", FAMILIES)
    get_settings.cache_clear()
    repo = MemoryRepository()
    snapshot = generate(FAMILIES[0], 0).to_snapshot()

    async def prepare():
        await repo.ensure_task15_session(42)
        await repo.advance_task15_problem(42, None, [snapshot])
        await repo.save_user_state(42, "task15")
        await repo.set_task15_condition_message(42, snapshot["problem_id"], 100)

    asyncio.run(prepare())
    bot = Bot("123456:TEST")
    sent = Message(message_id=102, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.session.make_request = AsyncMock(return_value=sent)
    app = create_app(repository=repo, bot=bot, run_schema_migrations=False)
    payload = {
        "update_id": 15001,
        "message": {
            "message_id": 101,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Student"},
            "text": snapshot["correct_answer"],
        },
    }
    try:
        with TestClient(app) as client:
            for _ in range(2):
                response = client.post(
                    "/telegram/webhook",
                    json=payload,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "oge15-test-secret"},
                )
                assert response.status_code == 200
        assert repo.updates[123456, 15001] == "processed"
        assert len(repo.attempts15[42]) == 1
        assert repo.outcomes15[42][snapshot["problem_id"]] == "solved"
        bot.session.make_request.assert_awaited_once()
    finally:
        get_settings.cache_clear()
