import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import BufferedInputFile, Chat, Message, User

from app.bot import router
from app.bot.presentation import send_photo
from app.math import oge18_scheduler
from app.math.oge18 import FAMILIES, from_snapshot, generate
from app.persistence.repository import MemoryRepository


def message(text="", mid=100):
    incoming = AsyncMock()
    incoming.from_user = User(id=42, is_bot=False, first_name="Student")
    incoming.message_id = mid
    incoming.text = text
    incoming.reply_to_message = None
    incoming.answer.return_value.message_id = mid + 1
    incoming.answer_photo.return_value.message_id = mid + 1
    return incoming


async def test_public_flag_hides_and_blocks_task18_and_forged_navigation():
    repo = MemoryRepository()
    incoming = message()
    await router.choose_number(incoming, repo)
    labels = [
        b.text
        for row in incoming.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert not any(text.startswith("№18") for text in labels)
    await router.choose_task18(incoming, repo)
    assert "выключены" in incoming.answer.await_args.args[0]
    assert await repo.task18_state(42) is None
    incoming.answer_photo.assert_not_awaited()


@pytest.mark.parametrize("family", (FAMILIES[0], "OGE18-A03"))
async def test_same_png_and_counts_on_resume_and_corruption_fails_closed(monkeypatch, family):
    monkeypatch.setattr(oge18_scheduler, "ENABLED_FAMILIES", (family,))
    repo = MemoryRepository()
    first = message()
    await router.choose_task18(first, repo)
    saved = await repo.task18_state(42)
    original = from_snapshot(saved["problem"])
    assert first.answer_photo.await_args.args[0].data == original.png_bytes
    assert saved["state"]["problem_prompt_message_id"] == 101
    await router.task18_answer(message("0", 102), repo)
    assert (await repo.task18_state(42))["state"]["attempts"] == 1
    await repo.save_user_state(42, "main_menu")
    resumed = message(mid=104)
    await router.continue_session(resumed, repo)
    assert resumed.answer_photo.await_args.args[0].data == original.png_bytes
    assert (await repo.task18_state(42))["state"]["attempts"] == 1
    saved["problem"]["image_sha256"] = "bad"
    broken = message(mid=106)
    assert not await router._send_task18_problem(broken, repo, action="resume")
    broken.answer_photo.assert_not_awaited()
    await router.task18_answer(message("4", 108), repo)
    assert (await repo.task18_state(42))["state"]["attempts"] == 1


@pytest.mark.parametrize(
    "display,error",
    (
        ("auto", None),
        ("png", None),
        ("auto", TelegramBadRequest),
        ("auto", TelegramNetworkError),
    ),
)
async def test_real_png_transport_media_fallback_and_ambiguous_timeout(display, error):
    bot = Bot("123456:TEST")
    sent = Message(message_id=91, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    method = SendRichMessage(chat_id=42, rich_message={"html": "test"})
    effect = error(method=method, message="unavailable") if error else None
    bot.send_rich_message = AsyncMock(return_value=sent, side_effect=effect)
    bot.send_photo = AsyncMock(return_value=sent)
    repo = MemoryRepository()
    await repo.set_math_display(42, display)
    incoming = Message(
        message_id=19,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Student"),
    ).as_(bot)
    problem = generate(FAMILIES[0], 42)
    photo = BufferedInputFile(problem.png_bytes, "oge18.png")
    # Exercise the existing rich media path with the same exact saved diagram.
    kwargs = {"caption": "Задание №18\nСторона клетки 1. Найдите m = AC/2."}
    try:
        if error is TelegramNetworkError:
            with pytest.raises(TelegramNetworkError):
                await send_photo(incoming, repo, photo, **kwargs)
            bot.send_photo.assert_not_awaited()
        else:
            result = await send_photo(incoming, repo, photo, **kwargs)
            assert result.message_id == 91
            if display == "auto" and error is None:
                payload = bot.send_rich_message.await_args.kwargs
                assert payload["rich_message"].media[0].media.media.data == problem.png_bytes
            else:
                bot.send_photo.assert_awaited_once()
                assert bot.send_photo.await_args.kwargs["photo"].data.startswith(b"\x89PNG")
        assert base64.b64decode(problem.to_snapshot()["png_base64"]) == problem.png_bytes
    finally:
        await bot.session.close()


def test_task18_duplicate_webhook_is_processed_once(monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "oge18-test-secret")
    monkeypatch.setattr(oge18_scheduler, "ENABLED_FAMILIES", FAMILIES)
    get_settings.cache_clear()
    repo = MemoryRepository()
    snapshot = generate(FAMILIES[0], 0).to_snapshot()

    async def prepare():
        await repo.ensure_task18_session(42)
        await repo.advance_task18_problem(42, None, [snapshot])
        await repo.save_user_state(42, "task18")
        await repo.set_task18_condition_message(42, snapshot["problem_id"], 100)

    asyncio.run(prepare())
    bot = Bot("123456:TEST")
    sent = Message(message_id=102, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.session.make_request = AsyncMock(return_value=sent)
    app = create_app(repository=repo, bot=bot, run_schema_migrations=False)
    payload = {
        "update_id": 18001,
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
                    headers={"X-Telegram-Bot-Api-Secret-Token": "oge18-test-secret"},
                )
                assert response.status_code == 200
        assert repo.updates[18001] == "processed"
        assert len(repo.attempts18[42]) == 1
        assert repo.outcomes18[42][snapshot["problem_id"]] == "solved"
        bot.session.make_request.assert_awaited_once()
    finally:
        get_settings.cache_clear()
