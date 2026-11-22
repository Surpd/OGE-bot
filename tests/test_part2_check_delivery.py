from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Chat, Message, User
from pydantic import SecretStr

from app.bot import part2_check
from app.bot.presentation import MathDeliveryUncertain
from app.config import Settings
from app.part2_grading import Assessment, Grade
from tests.test_inline_dispatcher_postgres import TelegramSession


@pytest.mark.parametrize("definite_rejection", [True, False])
@pytest.mark.parametrize("score", [1, 2])
async def test_photo_grade_delivery(monkeypatch, definite_rejection, score):
    class RejectGradePhoto(TelegramSession):
        async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
            if isinstance(method, SendPhoto):
                finish.assert_awaited_once()  # Result is persisted before delivery.
                self.calls.append(method)
                if definite_rejection:
                    raise TelegramBadRequest(method=method, message="PHOTO_INVALID_DIMENSIONS")
                raise TelegramNetworkError(method=method, message="response lost")
            return await super().make_request(bot, method, timeout)

    settings = Settings(oge_grading_enabled=True, openai_api_key=SecretStr("fake"))
    monkeypatch.setattr(part2_check, "get_settings", lambda: settings)
    monkeypatch.setattr(part2_check, "reserve", AsyncMock(return_value=(None, [{"photo": "page"}])))
    monkeypatch.setattr(part2_check, "clean_photo", lambda data: data)
    monkeypatch.setattr(part2_check, "inputs", lambda card, refs, text, photos: photos)

    @asynccontextmanager
    async def client(_):
        yield object()

    monkeypatch.setattr(part2_check, "open_client", client)
    monkeypatch.setattr(part2_check, "check_size", AsyncMock())
    dispatched = AsyncMock()
    finish = AsyncMock()
    monkeypatch.setattr(part2_check, "mark_dispatched", dispatched)
    monkeypatch.setattr(part2_check, "finish", finish)
    assessment = Assessment(
        status="graded",
        score=score,
        max_score=2,
        criterion_evidence=[{"criterion": "Преобразование", "student_evidence": "x=2"}],
        correct_steps=[r"Верно получено \(x=2\)."],
        errors=["Нет проверки корня."],
        feedback="Промежуточный результат верен.",
        next_step="Подставьте корень в исходное уравнение.",
        needs_review=False,
        confidence=0.9,
    )
    result = Grade(assessment, 30, 20, "mock", Decimal(0))
    assess = AsyncMock(return_value=result)
    monkeypatch.setattr(part2_check, "assess", assess)
    row = {
        "id": 32,
        "revision": 4,
        "number": 20,
        "scored": True,
        "solution_viewed_at": None,
        "draft": True,
        "card": {"visuals": [], "rubric": {"kind": "practice"}},
    }
    bank = SimpleNamespace(pool=object(), current=AsyncMock(return_value=row))
    repo = AsyncMock()
    repo.user_state.return_value = "part2"
    repo.math_display.return_value = "png"
    telegram = RejectGradePhoto()
    bot = Bot("123456:TEST", session=telegram)
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="photo.jpg", file_size=4))

    async def download_file(_path, *, destination):
        destination.write(b"page")

    bot.download_file = download_file
    message = Message(
        message_id=9,
        date=datetime.now(UTC),
        chat=Chat(id=-42, type="supergroup"),
        from_user=User(id=42, is_bot=False, first_name="Test"),
        message_thread_id=7,
        is_topic_message=True,
    ).as_(bot)

    try:
        if definite_rejection:
            await part2_check.check(message, repo, 42, row, bank)
        else:
            with pytest.raises(MathDeliveryUncertain):
                await part2_check.check(message, repo, 42, row, bank)
    finally:
        await telegram.close()

    assess.assert_awaited_once()
    assert assess.await_args.args[-1] == [b"page"]
    dispatched.assert_awaited_once_with(bank.pool, 32, 4)
    finish.assert_awaited_once_with(
        bank.pool, settings, 32, 4, result, dispatched=True, reason=None
    )
    assert [c.__api_method__ for c in telegram.calls] == (
        ["sendMessage", "sendPhoto", "sendMessage"]
        if definite_rejection
        else ["sendMessage", "sendPhoto"]
    )
    if definite_rejection:
        _, initial, fallback = telegram.calls
        assert isinstance(fallback, SendMessage)
        assert (fallback.chat_id, fallback.message_thread_id) == (
            initial.chat_id, initial.message_thread_id
        ) == (-42, 7)
        assert fallback.reply_markup is not None
        assert fallback.reply_markup == initial.reply_markup
        assert fallback.parse_mode == "HTML"
        assert fallback.text.count(f"Оценка: {score} из 2 баллов") == 1
        assert "Проверка сохранена в «Письменных работах»." in fallback.text
        assert "«Завершить» закрывает задание." in fallback.text
        assert "Верно получено x=2." in fallback.text
        assert ("Нет проверки корня." in fallback.text) == (score < 2)
        assert ("Подставьте корень в исходное уравнение." in fallback.text) == (score < 2)
        repo.set_navigation_message.assert_awaited_once()
    else:
        repo.set_navigation_message.assert_not_awaited()
