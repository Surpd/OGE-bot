"""Inline navigation; callbacks must claim the current persisted menu message."""

import secrets
from collections.abc import Awaitable, Callable
from typing import Any, cast

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callbacks import answer_callback
from app.bot.scenario_training import show_public_oge15
from app.persistence.repository import Repository
from app.persistence.scenario_repository import ScenarioPostgresRepository


def navigation_revision(markup: object) -> str | None:
    if not isinstance(markup, InlineKeyboardMarkup):
        return None
    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data and "~" in button.callback_data:
                return button.callback_data.rpartition("~")[2]
    return None


def prepare_navigation_markup(markup: object) -> object:
    """Each rendered keyboard has a revision, even when its message ID is reused."""
    if navigation_screen(markup) is None or navigation_revision(markup) is not None:
        return markup
    assert isinstance(markup, InlineKeyboardMarkup)
    revision = secrets.token_hex(6)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button.model_copy(update={"callback_data": f"{button.callback_data}~{revision}"})
                if button.callback_data
                else button
                for button in row
            ]
            for row in markup.inline_keyboard
        ]
    )


def navigation_screen(markup: object) -> str | None:
    if not isinstance(markup, InlineKeyboardMarkup):
        return None
    callbacks = {
        button.callback_data.partition("~")[0] if button.callback_data else None
        for row in markup.inline_keyboard
        for button in row
    }
    for value in callbacks:
        if value and value.startswith("nav:math:"):
            return "display_settings"
        if value and value.startswith("nav:training:"):
            return "number_selection"
        if value and value.startswith(("nav:family:", "nav:families:", "nav:begin:")):
            return f"family_selection:{value.split(':')[2]}"
    if "nav:task:6" in callbacks:
        return "number_selection"
    if "nav:details" in callbacks or any(
        value and value.startswith("progress:") for value in callbacks
    ):
        return "progress"
    if "nav:numbers" in callbacks:
        return "main_menu"
    return None


async def bind_navigation(
    message: Message,
    repository: Repository,
    user_id: int,
    screen: str,
    revision: str | None = None,
) -> None:
    await repository.set_navigation_message(user_id, screen, message.message_id, revision)


class NavigationMessage:
    """Use the tapping user, never the bot sender of the menu, for existing handlers."""

    def __init__(self, message: Message, callback: CallbackQuery, repository: Repository) -> None:
        self._message = message
        self._repository = repository
        self.from_user = callback.from_user
        self.text = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    async def answer(self, text: str, **kwargs: Any) -> Message:
        screen = navigation_screen(kwargs.get("reply_markup"))
        if screen is not None:
            try:
                edited = await self._message.edit_text(text, **kwargs)
                sent = edited if isinstance(edited, Message) else self._message
            except TelegramBadRequest:
                # Expired/deleted menus may no longer be editable. Create one
                # replacement; transport/network failures are not retried here.
                sent = await self._message.answer(text, **kwargs)
            await bind_navigation(
                sent,
                self._repository,
                self.from_user.id,
                screen,
                navigation_revision(kwargs.get("reply_markup")),
            )
        else:
            sent = await self._message.answer(text, **kwargs)
        return sent


async def show_display_options(message: Message, repository: Repository) -> None:
    from app.bot.presentation import send_text

    if message.from_user is None:
        return
    user_id = message.from_user.id
    await repository.save_user_state(user_id, "display_settings")
    mode = await repository.math_display(user_id)
    label = "картинкой" if mode == "png" else "обычное оформление"
    await send_text(
        message,
        repository,
        f"Вид формул: {label}.\n\n"
        "Если формулы не видны в вашем Telegram, выберите «Картинкой», "
        "затем продолжите сохранённое задание из меню.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Обычное оформление", callback_data="nav:math:auto"),
                    InlineKeyboardButton(text="Картинкой", callback_data="nav:math:png"),
                ],
                [InlineKeyboardButton(text="В меню", callback_data="nav:main")],
            ]
        ),
    )


async def navigation_callback(
    callback: CallbackQuery,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    from app.bot import router as handlers

    if not isinstance(callback.message, Message) or not callback.data:
        await answer_callback(callback)
        return
    data, _, revision = callback.data.partition("~")
    targets = {
        "nav:main": handlers.return_to_menu,
        "nav:numbers": handlers.choose_number,
        "nav:resume": handlers.continue_session,
        "nav:progress": handlers.show_progress,
        "nav:details": handlers.show_progress_details,
        "nav:display": show_display_options,
    }
    target = targets.get(data)
    if data == "nav:oge15":
        target = show_public_oge15
    if data.startswith("nav:task:"):
        from app.bot.trainings import TRAININGS

        value = data.removeprefix("nav:task:")
        training = next((item for item in TRAININGS if str(item.number) == value), None)
        if training is not None and training.available:
            target = getattr(handlers, f"choose_task{training.number}", None)
    training_parts = data.split(":")
    training_action: tuple[str, int, str] | None = None
    if (
        len(training_parts) == 5
        and training_parts[:2] == ["nav", "training"]
        and training_parts[3].isascii()
        and training_parts[3].isdigit()
    ):
        training_action = (training_parts[2], int(training_parts[3]), training_parts[4])
    family_parts = data.split(":")
    family_action: tuple[int, str | None] | None = None
    if len(family_parts) in {3, 4} and family_parts[:1] == ["nav"]:
        from app.bot.training_engine import NUMERIC_TRAININGS

        action, value = family_parts[1:3]
        if value.isascii() and value.isdigit() and int(value) in NUMERIC_TRAININGS:
            if action in {"families", "task"}:
                family_action = (int(value), None)
            elif action == "family" and len(family_parts) == 4:
                family_action = (int(value), family_parts[3])
            elif action == "begin":
                target = getattr(handlers, f"choose_task{int(value)}")
    progress_page = data.removeprefix("progress:") if data.startswith("progress:") else None
    display_mode = data.removeprefix("nav:math:") if data.startswith("nav:math:") else None
    if display_mode not in {None, "auto", "png"}:
        await answer_callback(callback, "Этот вид формул недоступен.")
        return
    if (
        target is None and progress_page is None and family_action is None
        and display_mode is None and training_action is None
    ):
        await answer_callback(callback, "Этот раздел недоступен.")
        return
    if not await repository.claim_navigation_message(
        callback.from_user.id, callback.message.message_id, revision or None
    ):
        await answer_callback(callback, "Это меню устарело. Откройте /start.")
        return
    if oge15_repository is not None and (
        data
        in {
            "nav:main", "nav:numbers", "nav:progress", "nav:details", "nav:display",
            "nav:settings",
        }
        or data.startswith("nav:task:")
        or data.startswith("nav:training:")
    ):
        await oge15_repository.pause_foreground(callback.from_user.id)
    message = cast(Message, NavigationMessage(callback.message, callback, repository))
    if display_mode is not None:
        await repository.set_math_display(callback.from_user.id, display_mode)
        await show_display_options(message, repository)
    elif family_action is not None:
        from app.bot.family_selection import select_family, show_families

        number, selection = family_action
        if selection is None:
            await show_families(message, repository, number)
        else:
            await select_family(message, repository, number, selection)
    elif progress_page is not None:
        from app.bot.presentation import send_text
        from app.bot.progress import progress_keyboard, render_progress
        from app.persistence.training_insights import training_insights

        await repository.save_user_state(callback.from_user.id, "progress")
        insights = await training_insights(repository, callback.from_user.id, progress_page)
        total = insights["page_total"]
        await send_text(
            message,
            repository,
            render_progress(insights, progress_page),
            reply_markup=progress_keyboard(progress_page, total),
        )
    elif data == "nav:oge15":
        await show_public_oge15(message, oge15_repository, repository)
    elif training_action is not None:
        action, number, problem_id = training_action
        await handlers.saved_training_navigation(
            message, repository, callback.from_user.id, action, number, problem_id,
            oge15_repository,
        )
    elif target is not None:
        if data == "nav:resume":
            await handlers.continue_session(
                message,
                repository,
                oge15_repository,
                user_id_override=callback.from_user.id,
            )
        elif data == "nav:main":
            await handlers.return_to_menu(
                message,
                repository,
                oge15_repository,
                user_id_override=callback.from_user.id,
            )
        else:
            handler = cast(Callable[[Message, Repository], Awaitable[None]], target)
            await handler(message, repository)
    # Complete the guarded transition before an optional notification can fail.
    await answer_callback(callback)
