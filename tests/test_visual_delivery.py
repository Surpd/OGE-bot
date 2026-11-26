from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
    User,
)
from PIL import Image
from test_inline_dispatcher_postgres import TelegramSession

from app.bot import visual_delivery as delivery
from app.bot.navigation import NavigationMessage, navigation_revision, navigation_screen
from app.bot.presentation import send_text
from app.bot.visual_models import VisualCard
from app.config import Settings
from app.config import test_settings as current_settings
from app.persistence.repository import MemoryRepository

CARD = VisualCard("numbers", "Выбери номер")
CHECKPOINT = VisualCard("training_result", "Результат тренировки")
FINISHED = VisualCard("training_result", "Тренировка завершена")
JOURNAL = VisualCard("progress_journal", "История и ошибки")
VIEWER = User(id=42, is_bot=False, first_name="QA")


class CardSession(TelegramSession):
    photo_error = None
    media_error = None

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        error = {"sendPhoto": self.photo_error, "editMessageMedia": self.media_error}.get(
            method.__api_method__
        )
        if error is not None:
            self.calls.append(method)
            raise error(method=method, message="synthetic delivery failure")
        return await super().make_request(bot, method, timeout)


def keyboard(label):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="nav:numbers:0")],
    ])


def result_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К тренировкам", callback_data="train:hub")],
    ])


@pytest.fixture
def flags():
    token = current_settings.set(Settings(_env_file=None, oge_visual_numbers_enabled=True))
    delivery._render_menu_png.cache_clear()
    try:
        yield
    finally:
        current_settings.reset(token)
        delivery._render_menu_png.cache_clear()


@pytest.fixture
def synthetic_png(monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, "PNG")
    captured = []

    def render(card):
        captured.append(card)
        return buffer.getvalue()

    monkeypatch.setattr(delivery, "_render_png", render)
    return captured


def source(bot, viewer=VIEWER):
    return Message(message_id=10, date=datetime.now(UTC), chat=Chat(id=42, type="private"),
                   from_user=viewer).as_(bot)


async def test_photo_reuses_static_bytes_and_binds_returned_message(flags, synthetic_png):
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    await repository.save_user_state(42, "number_selection")
    legacy = keyboard("Текстовая кнопка")
    visual = keyboard("Кнопка PNG")

    first = await send_text(
        source(bot), repository, "Прежний каталог", reply_markup=legacy,
        visual=CARD, visual_reply_markup=visual,
    )
    proxy = cast(Message, NavigationMessage(first, CallbackQuery(
        id="qa", from_user=VIEWER, chat_instance="qa", message=first,
    ), repository))
    second = await send_text(proxy, repository, "Прежний каталог", reply_markup=legacy, visual=CARD)

    assert [method.__api_method__ for method in transport.calls] == [
        "sendPhoto", "editMessageMedia",
    ]
    assert synthetic_png == [CARD]
    assert first.photo and second.photo and first.message_id == second.message_id
    assert first.reply_markup.inline_keyboard[0][0].text == "Кнопка PNG"
    revision = navigation_revision(second.reply_markup)
    assert revision != navigation_revision(first.reply_markup)
    assert not await repository.claim_navigation_message(42, first.message_id, navigation_revision(
        first.reply_markup
    ))
    assert await repository.claim_navigation_message(42, second.message_id, revision)


@pytest.mark.parametrize("failure", ["render", "photo", "off", "other-viewer", "companion-only"])
async def test_definite_failure_or_disabled_keeps_original_keyboard(
    flags, synthetic_png, monkeypatch, failure,
):
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    await repository.save_user_state(42, "number_selection")
    if failure == "render":
        def failed(card):
            raise OSError("unavailable")

        monkeypatch.setattr(delivery, "_render_png", failed)
    elif failure == "photo":
        transport.photo_error = TelegramBadRequest
    else:
        current_settings.set(Settings(
            _env_file=None,
            oge_visual_numbers_enabled=failure != "off",
            oge_visual_companion_only=failure == "companion-only",
            oge_visual_user_ids="43" if failure == "other-viewer" else "",
        ))

    result = await send_text(
        source(bot), repository, "Прежний каталог", visual=CARD,
        reply_markup=keyboard("Рабочий маршрут"), visual_reply_markup=keyboard("Новый маршрут"),
    )
    expected = ["sendPhoto", "sendMessage"] if failure == "photo" else ["sendMessage"]
    assert [method.__api_method__ for method in transport.calls] == expected
    assert "Прежний каталог" in result.text
    assert result.reply_markup.inline_keyboard[0][0].text == "Рабочий маршрут"
    assert await repository.claim_navigation_message(
        42, result.message_id, navigation_revision(result.reply_markup)
    )


async def test_ambiguous_delivery_does_not_publish_duplicate(flags, synthetic_png):
    transport = CardSession()
    transport.photo_error = TelegramNetworkError
    bot = Bot("123456:TEST", session=transport)

    with pytest.raises(TelegramNetworkError):
        await send_text(source(bot), MemoryRepository(), "Прежний каталог", visual=CARD,
                        reply_markup=keyboard("Меню"))

    assert [method.__api_method__ for method in transport.calls] == ["sendPhoto"]


async def test_visual_reply_preserves_dashboard_anchor(flags, synthetic_png):
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    original = await send_text(source(bot), repository, "Исходное меню")
    sent = await send_text(
        source(bot), repository, "Прежний каталог",
        visual=CARD, reply_markup=keyboard("К номерам"),
        reply_parameters=ReplyParameters(message_id=original.message_id),
    )
    assert transport.calls[-1].reply_parameters.message_id == original.message_id
    assert sent.reply_to_message.message_id == original.message_id


async def test_menu_photo_does_not_replace_existing_progress_dashboard(flags, synthetic_png):
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    dashboard_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="По номерам", callback_data="progress:details")],
    ])
    first = await send_text(source(bot), repository, "Прогресс", visual=CARD,
                            reply_markup=dashboard_markup)
    proxy = cast(Message, NavigationMessage(first, CallbackQuery(
        id="qa", from_user=VIEWER, chat_instance="qa", message=first,
    ), repository))
    second = await send_text(proxy, repository, "Каталог", visual=CARD,
                             reply_markup=keyboard("Номера"))
    assert [method.__api_method__ for method in transport.calls] == ["sendPhoto", "sendPhoto"]
    assert first.message_id != second.message_id


@pytest.mark.parametrize("edit_rejected", [False, True])
async def test_progress_photo_edit_retains_summary_reply_and_revises_keyboard(
    flags, synthetic_png, edit_rejected,
):
    current_settings.set(Settings(
        _env_file=None, oge_visual_progress_journal_enabled=True, oge_visual_user_ids="42",
    ))
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    await repository.save_user_state(42, "progress")
    summary = await send_text(source(bot), repository, "Твой прогресс")
    anchor = ReplyParameters(message_id=summary.message_id)

    def journal_keyboard(label, page):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"progress:{page}")],
        ])

    first = await send_text(
        source(bot), repository, "Все задания", visual=JOURNAL, reply_parameters=anchor,
        reply_markup=journal_keyboard("С ошибками", "errors:0"),
    )
    proxy = cast(Message, NavigationMessage(first, CallbackQuery(
        id="qa", from_user=VIEWER, chat_instance="qa", message=first,
    ), repository))
    if edit_rejected:
        transport.media_error = TelegramBadRequest
    before = len(transport.calls)
    second = await send_text(
        proxy, repository, "Задания с ошибками", visual=JOURNAL, reply_parameters=anchor,
        reply_markup=journal_keyboard("Все задания", "history:0"), edit_progress=True,
    )
    expected = ["editMessageMedia"]
    if edit_rejected:
        expected.append("sendPhoto")
    assert [method.__api_method__ for method in transport.calls[before:]] == expected
    assert (first.message_id != second.message_id) == edit_rejected
    assert second.reply_to_message.message_id == summary.message_id
    assert second.reply_markup.inline_keyboard[0][0].text == "Все задания"
    assert not await repository.claim_navigation_message(
        42, first.message_id, navigation_revision(first.reply_markup),
    )
    assert await repository.claim_navigation_message(
        42, second.message_id, navigation_revision(second.reply_markup),
    )


@pytest.mark.parametrize("allowlist", ["", "43", "42,broken", "42,43", "42"])
def test_progress_route_requires_explicit_viewer_without_affecting_other_cards(flags, allowlist):
    current_settings.set(Settings(
        _env_file=None, oge_visual_number_progress_enabled=True,
        oge_visual_progress_journal_enabled=True, oge_visual_numbers_enabled=True,
        oge_visual_training_result_enabled=True, oge_visual_user_ids=allowlist,
    ))
    message = source(None)
    for screen in ("progress_numbers", "number_progress", "progress_journal"):
        assert delivery.visual_enabled(screen, message) == (allowlist == "42")
        assert not delivery.visual_enabled(screen, message, 44)
    for screen in ("numbers", "training_result"):
        assert delivery.visual_enabled(screen, message) == (allowlist in {"", "42", "42,43"})


def test_second_part_requires_both_flags_and_private_viewer(flags):
    current_settings.set(Settings(_env_file=None, oge_visual_part2_enabled=True))
    message = source(None)
    assert not delivery.visual_enabled("part2", message)
    current_settings.set(Settings(
        _env_file=None, oge_visual_part2_enabled=True, oge_part2_enabled=True,
        oge_visual_user_ids="42, 43",
    ))
    assert delivery.visual_enabled("part2", message)
    assert not delivery.visual_enabled("part2", message, 44)
    assert not delivery.visual_enabled("part2", message.model_copy(update={
        "chat": Chat(id=-42, type="group"),
    }))


def test_adaptive_written_picker_returns_to_training_number_selection(flags):
    from app.bot.adaptive import area_card

    current_settings.set(Settings(_env_file=None, oge_part2_enabled=True))
    _, markup = area_card(1)
    assert navigation_screen(markup) == "trainings"


@pytest.mark.parametrize("transport_path", ["photo", "cover", "caption", "text"])
async def test_finish_replaces_checkpoint_in_place(
    flags, synthetic_png, monkeypatch, transport_path,
):
    current_settings.set(Settings(_env_file=None, oge_visual_training_result_enabled=True))
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    await repository.save_user_state(42, "trainings")

    def failed(card):
        raise OSError("synthetic render failure")

    if transport_path == "text":
        monkeypatch.setattr(delivery, "_render_png", failed)
    first = await send_text(
        source(bot), repository, "Результат тренировки\n\nХочешь продолжить?",
        visual=CHECKPOINT, visual_caption="Хочешь продолжить?",
    )
    if transport_path == "cover":
        monkeypatch.setattr(delivery, "_render_png", failed)
    elif transport_path == "caption":
        transport.media_error = TelegramBadRequest

    finished = await send_text(
        first, repository, "Тренировка завершена\nРешено верно: 8 из 10",
        visual=FINISHED, edit_existing=True, reply_markup=result_keyboard(), user_id_override=42,
    )
    methods = {
        "photo": ["sendPhoto", "editMessageMedia"],
        "cover": ["sendPhoto", "editMessageMedia"],
        "caption": ["sendPhoto", "editMessageMedia", "editMessageMedia", "editMessageCaption"],
        "text": ["sendMessage", "editMessageText"],
    }
    assert [method.__api_method__ for method in transport.calls] == methods[transport_path]
    assert finished.message_id == first.message_id
    assert finished.reply_markup.inline_keyboard[0][0].text == "К тренировкам"
    assert "Хочешь продолжить?" in (first.caption or first.text)
    assert "Хочешь продолжить?" not in (finished.caption or finished.text or "")
    if transport_path == "cover":
        assert transport.calls[-1].media.media.filename == "bop-finished-result.png"
    if transport_path != "photo":
        assert "8 из 10" in (finished.caption or finished.text)
    assert await repository.claim_navigation_message(
        42, finished.message_id, navigation_revision(finished.reply_markup)
    )


async def test_ambiguous_finish_edit_does_not_retry(flags, synthetic_png):
    current_settings.set(Settings(_env_file=None, oge_visual_training_result_enabled=True))
    transport = CardSession()
    bot = Bot("123456:TEST", session=transport)
    repository = MemoryRepository()
    first = await send_text(source(bot), repository, "Результат тренировки", visual=CHECKPOINT)
    transport.media_error = TelegramNetworkError

    with pytest.raises(TelegramNetworkError):
        await send_text(first, repository, "Тренировка завершена", visual=FINISHED,
                        edit_existing=True, user_id_override=42)

    assert [call.__api_method__ for call in transport.calls] == ["sendPhoto", "editMessageMedia"]
