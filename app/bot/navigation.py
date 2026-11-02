"""Inline navigation; callbacks must claim the current persisted menu message."""

from typing import Any, cast

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.persistence.repository import Repository


def navigation_screen(markup: object) -> str | None:
    if not isinstance(markup, InlineKeyboardMarkup):
        return None
    callbacks = {button.callback_data for row in markup.inline_keyboard for button in row}
    for value in callbacks:
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
    message: Message, repository: Repository, user_id: int, screen: str
) -> None:
    await repository.set_navigation_message(user_id, screen, message.message_id)


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
        sent = await self._message.answer(text, **kwargs)
        screen = navigation_screen(kwargs.get("reply_markup"))
        if screen is not None:
            await bind_navigation(sent, self._repository, self.from_user.id, screen)
        return sent


async def navigation_callback(callback: CallbackQuery, repository: Repository) -> None:
    from app.bot import router as handlers

    if not isinstance(callback.message, Message) or not callback.data:
        await callback.answer()
        return
    data = callback.data
    targets = {
        "nav:main": handlers.return_to_menu,
        "nav:numbers": handlers.choose_number,
        "nav:resume": handlers.continue_session,
        "nav:progress": handlers.show_progress,
        "nav:details": handlers.show_progress_details,
    }
    target = targets.get(data)
    if data.startswith("nav:task:"):
        from app.bot.trainings import TRAININGS

        value = data.removeprefix("nav:task:")
        training = next((item for item in TRAININGS if str(item.number) == value), None)
        if training is not None and training.available:
            target = getattr(handlers, f"choose_task{training.number}", None)
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
    if target is None and progress_page is None and family_action is None:
        await callback.answer("Этот раздел недоступен.")
        return
    if not await repository.claim_navigation_message(
        callback.from_user.id, callback.message.message_id
    ):
        await callback.answer("Это меню устарело. Откройте /start.")
        return
    await callback.answer()
    message = cast(Message, NavigationMessage(callback.message, callback, repository))
    if family_action is not None:
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
        insights = await training_insights(repository, callback.from_user.id)
        section = progress_page.partition(":")[0]
        total = (
            len(insights.get(section, [])) if section in {"families", "history", "errors"} else 0
        )
        await send_text(
            message,
            repository,
            render_progress(insights, progress_page),
            reply_markup=progress_keyboard(progress_page, total),
        )
    elif target is not None:
        await target(message, repository)
