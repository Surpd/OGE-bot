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
    if any(c and c.startswith("nav:numbers:") for c in callbacks) or (
        "nav:oge15" in callbacks and "nav:task:6" in callbacks
    ):
        return "number_selection"
    if any(c and c.startswith("nav:tr:") for c in callbacks):
        return "number_selection"
    if any(c and c.startswith("p2:apitest:") for c in callbacks):
        return "api_test"
    if "nav:numbers" in callbacks and any(
        c and c.startswith(
            ("p2:open:", "p2:menu:", "p2:drafts:", "p2:r:", "p2:intro:", "p2:resume:")
        )
        for c in callbacks
    ):
        return "part2_menu"
    if "nav:task:6" not in callbacks and any(c and c.startswith("p2:") for c in callbacks):
        return "part2"
    for value in callbacks:
        if value and value.startswith("nav:math:"):
            return "display_settings"
        if value and value.startswith(("nav:family:", "nav:families:", "nav:begin:")):
            return f"family_selection:{value.split(':')[2]}"
    if any(value and value.startswith("replay:") for value in callbacks):
        return "error_replay"
    if "nav:details" in callbacks or "nav:progress_text" in callbacks or any(
        value and value.startswith("progress:") for value in callbacks
    ):
        return "progress"
    if "nav:task:6" in callbacks:
        return "number_selection"
    if any(
        value
        and value.startswith(
            (
                "oge15:story:", "oge15:mode:", "oge15:start:", "oge15:return:",
                "oge15:new:", "oge15:unfinished", "oge15:resume:", "oge15:restart:",
                "oge15:new-confirm:", "oge15:restart-confirm:", "oge15:restart-cancel:",
                "oge15:rc:", "oge15:rx:",
            )
        )
        for value in callbacks
    ):
        return "oge15_menu"
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

    def __init__(
        self, message: Message, callback: CallbackQuery, repository: Repository,
        *, edit_navigation: bool = True,
    ) -> None:
        self._message = message
        self._edit_navigation = edit_navigation
        self._repository = repository
        self.from_user = callback.from_user
        self.text = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    async def answer(self, text: str, **kwargs: Any) -> Message:
        screen = navigation_screen(kwargs.get("reply_markup"))
        if screen is not None and self._edit_navigation:
            try:
                edit_kwargs = kwargs.copy()
                edit_kwargs.pop("reply_parameters", None)
                edited = await self._message.edit_text(text, **edit_kwargs)
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
        "nav:mixed": handlers.start_mixed,
        "nav:progress": handlers.show_progress,
        "nav:progress_text": getattr(handlers, "show_progress_text", handlers.show_progress),
        "nav:details": handlers.show_progress_details,
        "nav:display": show_display_options,
    }
    target = targets.get(data)
    number_page = None
    if data.startswith("nav:numbers:"):
        value = data.removeprefix("nav:numbers:")
        if value.isascii() and value.isdigit() and len(value) <= 2:
            number_page = int(value)
            target = handlers.choose_number
    if data == "nav:oge15":
        target = show_public_oge15
    oge15_number: int | None = None
    if data.startswith("nav:oge15:"):
        value = data.removeprefix("nav:oge15:")
        if value.isascii() and value.isdigit() and int(value) in range(1, 6):
            oge15_number = int(value)
            target = show_public_oge15
    if data.startswith("nav:task:"):
        from app.bot.trainings import TRAININGS

        value = data.removeprefix("nav:task:")
        training = next((item for item in TRAININGS if str(item.number) == value), None)
        if training is not None and training.available:
            target = getattr(handlers, f"choose_task{training.number}", None)
    training_parts = data.split(":")
    training_action: tuple[str, int, str] | None = None
    training_codes = {"c": "continue", "r": "restart", "y": "confirm", "n": "cancel"}
    if (
        len(training_parts) == 5
        and training_parts[:2] == ["nav", "tr"]
        and training_parts[2] in training_codes
        and training_parts[3].isascii()
        and training_parts[3].isdigit()
    ):
        training_action = (
            training_codes[training_parts[2]], int(training_parts[3]), training_parts[4]
        )
    family_parts = data.split(":")
    family_page = 0
    family_action: tuple[int, str | None] | None = None
    if len(family_parts) in {3, 4} and family_parts[:1] == ["nav"]:
        from app.persistence.rotation_history import enabled

        action, value = family_parts[1:3]
        if value.isascii() and value.isdigit() and 6 <= int(value) <= 19 and enabled(int(value)):
            if action == "families" or (action == "task" and target is not None):
                if len(family_parts) == 4:
                    raw = family_parts[3]
                    if not raw.isascii() or not raw.isdigit() or len(raw) > 2:
                        await answer_callback(callback, "Эта страница недоступна.")
                        return
                    family_page = int(raw)
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
        and not data.startswith(("replay:", "p2:"))
    ):
        await answer_callback(callback, "Этот раздел недоступен.")
        return
    if data.startswith("p2:apitest:"):
        markup = callback.message.reply_markup
        if (callback.message.chat.type != "private" or markup is None or
            not any(b.callback_data == callback.data for row in markup.inline_keyboard for b in row)
            or await repository.user_state(callback.from_user.id) != "api_test"):
            await answer_callback(callback, "Откройте /api_test для подтверждения.")
            return
    if not await repository.claim_navigation_message(
        callback.from_user.id, callback.message.message_id, revision or None
    ):
        await answer_callback(callback, "Это меню устарело. Откройте /start.")
        return
    if oge15_repository is not None and (
        data
        in {
            "nav:main", "nav:numbers", "nav:mixed", "nav:progress", "nav:progress_text",
            "nav:details", "nav:display",
            "nav:settings",
        }
        or data.startswith(("nav:task:", "p2:"))
        or data.startswith("nav:tr:")
    ):
        await oge15_repository.pause_foreground(callback.from_user.id)
    # Written condition IDs must never be reused by editing another card in place.
    message = cast(Message, NavigationMessage(
        callback.message, callback, repository, edit_navigation=not data.startswith("p2:")
    ))
    if data.startswith("p2:"):
        from app.bot.part2 import action as part2_action
        await answer_callback(callback)
        await part2_action(message, repository, callback.from_user.id, data)
        return
    if display_mode is not None:
        await repository.set_math_display(callback.from_user.id, display_mode)
        await show_display_options(message, repository)
    elif family_action is not None:
        from app.bot.family_selection import select_family, show_families

        number, selection = family_action
        if data.startswith("nav:task:") and await handlers._show_saved_training_choice(
            message, repository, number, callback.from_user.id
        ):
            await answer_callback(callback)
            return
        if selection is None:
            await show_families(message, repository, number, family_page)
        else:
            await select_family(message, repository, number, selection)
    elif number_page is not None:
        await handlers.choose_number(message, repository, oge15_repository, page=number_page)
    elif progress_page is not None:
        from app.bot.progress import progress_navigation

        await progress_navigation(message, repository, callback.from_user.id, progress_page)
    elif data.startswith("replay:"):
        from app.bot.error_replay import callback as replay_callback

        await replay_callback(callback, repository)
        return
    elif data == "nav:oge15":
        await show_public_oge15(message, oge15_repository, repository)
    elif oge15_number is not None:
        await show_public_oge15(
            message, oge15_repository, repository, selected_number=oge15_number
        )
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
