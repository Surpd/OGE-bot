"""Owner-only Telegram controller for analytics in the isolated companion bot."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InputMediaPhoto,
    Message,
)

from app.admin.presentation import AdminView, render_admin_view

PERIODS = {"today", "7", "28"}
logger = logging.getLogger("oge_trainer")


def start_payload(text: str | None) -> str:
    words = (text or "").split(maxsplit=1)
    return words[1].strip() if len(words) == 2 else ""


def _parse_action(action: str, state: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Return view, load args, and stable state key for a compact callback action."""
    period = state.get("admin_period", "7")
    if period not in PERIODS:
        period = "7"
    is_period_filter = action.startswith("period:")
    is_detail_toggle = action in {"expand", "collapse"}
    if is_detail_toggle:
        state["admin_expanded"] = action == "expand"
        action = state.get("admin_screen", "home")
    if is_period_filter:
        candidate = action.partition(":")[2]
        if candidate in PERIODS:
            state["admin_period"] = period = candidate
        action = state.get("admin_screen", "home")
    if action == "refresh":
        action = state.get("admin_screen", "home")
        if action not in {
            "home",
            "usage",
            "learners",
            "learner",
            "tasks",
            "types",
            "task",
            "replays",
            "written",
            "system",
            "cost",
            "tools",
        }:
            action = "home"
        state["admin_refresh"] = True
    args: dict[str, Any] = {}
    screen = action
    try:
        if action.startswith("learners:"):
            screen = "learners"
            args["page"] = max(0, int(action.split(":", 1)[1]))
        elif action.startswith("learner:"):
            screen = "learner"
            args["key"] = action.split(":", 1)[1]
        elif action.startswith("types:"):
            _, number, page, sort = (action.split(":", 3) + ["sample"] * 4)[:4]
            screen = "types"
            args.update(number=int(number), page=max(0, int(page)), sort=sort)
        elif action.startswith("tasks:"):
            screen = "tasks"
            args["page"] = max(0, int(action.split(":", 1)[1]))
        elif action.startswith("task:"):
            screen = "task"
            args["number"] = int(action.split(":", 1)[1])
        elif action.startswith("detail:"):
            _, number, index = action.split(":", 2)
            screen = "task"
            family_keys = state.get("admin_type_keys", [])
            selected = int(index)
            if selected < 0 or selected >= len(family_keys):
                raise ValueError("Invalid family selection")
            args.update(number=int(number), key=family_keys[selected])
        elif action.startswith("written:"):
            screen = "written"
            parts = action.split(":")
            args["number"] = int(parts[1])
            if len(parts) == 3:
                args["page"] = max(0, int(parts[2]))
        elif action.startswith("replays:"):
            screen = "replays"
            args["page"] = max(0, int(action.split(":", 1)[1]))
    except (ValueError, TypeError, IndexError):
        screen, args = "home", {}
    if (is_period_filter or is_detail_toggle) and isinstance(state.get("admin_args"), dict):
        args = dict(state["admin_args"])
    if screen not in {
        "home",
        "usage",
        "learners",
        "learner",
        "tasks",
        "types",
        "task",
        "replays",
        "written",
        "system",
        "cost",
        "tools",
    }:
        screen, args = "home", {}
    return screen, args, period


async def present_admin(
    message: Message,
    state: dict[str, Any],
    service: Any,
    companion: Any,
    *,
    action: str = "home",
    callback: CallbackQuery | None = None,
) -> None:
    # Prepare navigation state separately. A failed Telegram delivery must leave
    # the currently visible menu revision valid and usable.
    next_state = deepcopy(state)
    next_state["active"] = False
    next_state["revision"] = None
    next_state["actions"] = []
    is_refresh = action == "refresh"
    is_back = action == "back"
    last_args = next_state.get("admin_args", {})
    if is_back:
        history = next_state.get("admin_history", [])
        previous = history.pop() if history else state.get("admin_back")
        next_state["admin_history"] = history
        if isinstance(previous, dict):
            action = previous.get("action", "home")
            last_args = previous.get("args", {})
            next_state["admin_expanded"] = bool(previous.get("expanded", False))
        else:
            action = "home"
            next_state["admin_expanded"] = False
    screen, args, period = _parse_action(action, next_state)
    if is_back and isinstance(last_args, dict):
        args = dict(last_args)
    if is_refresh and not args and isinstance(last_args, dict):
        args = dict(last_args)
    if (
        not is_back
        and action not in {"refresh", "expand", "collapse"}
        and not action.startswith("period:")
    ):
        same_report = (
            callback is not None
            and screen == state.get("admin_screen")
            and isinstance(last_args, dict)
            and args.get("number", 0) == last_args.get("number", 0)
            and args.get("key", "") == last_args.get("key", "")
        )
        if not same_report:
            next_state["admin_expanded"] = False
    refresh = bool(next_state.pop("admin_refresh", False))
    revision = secrets.token_hex(5)
    if callback is not None:
        await callback.answer()
    report = None
    try:
        if screen != "tools":
            report = await service.load(screen, period, refresh=refresh, **args)
    except Exception as exc:
        # Operational detail stays in server logs; this private view gets no exception text.
        logger.warning("admin_report_failed view=%s type=%s", screen, type(exc).__name__)
    data: Mapping[str, Any] = getattr(report, "data", {}) if report is not None else {}
    unavailable = getattr(report, "unavailable", None if screen == "tools" else "unavailable")
    data = dict(data)
    if unavailable:
        data["unavailable"] = unavailable
    if screen == "types":
        next_state["admin_type_keys"] = [
            str(row.get("family_id", "")) for row in data.get("rows", [])
        ]
    username = getattr(getattr(companion, "identity", None), "username", None)
    if not username and getattr(companion, "bot", None):
        username = getattr(companion.bot, "username", None)
    tools_url = f"https://t.me/{username}?start=qa" if username else None
    view = await asyncio.to_thread(
        render_admin_view,
        screen,
        data,
        revision=revision,
        period=period,
        companion_status=getattr(companion, "status", "unavailable"),
        release=getattr(companion, "sha", ""),
        tools_url=tools_url,
        window=getattr(report, "window", None),
        learner_id=args.get("key", ""),
        number=args.get("number", 0),
        page=args.get("page", 0),
        sort=args.get("sort", "sample"),
        family_id=args.get("key", "") if screen == "task" else "",
        updated_at=getattr(report, "updated_at", None),
        expanded=bool(next_state.get("admin_expanded")),
    )
    markup = view.markup
    next_state.update(
        {
            "admin_active": True,
            "admin_screen": screen,
            "admin_args": args,
            "admin_revision": revision,
            "admin_actions": [
                button.callback_data.split(":", 2)[2]
                for row in markup.inline_keyboard
                for button in row
                if button.callback_data and button.callback_data.startswith(f"adm:{revision}:")
            ],
        }
    )
    if callback is not None and bool(message.photo) == (view.photo is not None):
        try:
            if view.photo is not None:
                media = InputMediaPhoto(
                    media=BufferedInputFile(view.photo, filename="bop-admin.png"),
                    caption=view.caption,
                    parse_mode="HTML",
                )
                edited = await message.edit_media(media=media, reply_markup=markup)
            else:
                edited = await message.edit_text(
                    view.text,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
        except TelegramBadRequest:
            # Only a definitive edit rejection permits a replacement send.
            pass
        else:
            next_state["admin_menu"] = (
                edited.message_id if isinstance(edited, Message) else message.message_id
            )
            _replace_state(state, next_state)
            return
    old_message_id = message.message_id if callback is not None else next_state.get("admin_menu")
    sent = await _send_view(message, view)
    next_state["admin_menu"] = sent.message_id
    _replace_state(state, next_state)
    await _delete_previous_menu(message, old_message_id, sent.message_id)


def _replace_state(state: dict[str, Any], next_state: dict[str, Any]) -> None:
    state.clear()
    state.update(next_state)


async def _send_view(message: Message, view: AdminView) -> Message:
    if view.photo is not None:
        try:
            return await message.answer_photo(
                BufferedInputFile(view.photo, filename="bop-admin.png"),
                caption=view.caption,
                parse_mode="HTML",
                reply_markup=view.markup,
            )
        except TelegramBadRequest as exc:
            logger.warning("admin_photo_rejected type=%s", type(exc).__name__)
    return await message.answer(
        view.text,
        reply_markup=view.markup,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _delete_previous_menu(message: Message, previous_id: object, replacement_id: int) -> None:
    if not isinstance(previous_id, int) or previous_id == replacement_id:
        return
    bot = message.bot
    if bot is None:
        return
    try:
        await bot.delete_message(message.chat.id, previous_id)
    except TelegramAPIError as exc:
        # A replaced message can no longer authorize callbacks. Keep Telegram's
        # harmless cleanup failure out of the report path.
        logger.info("admin_previous_menu_cleanup_rejected type=%s", type(exc).__name__)


async def handle_admin_update(
    message: Message,
    state: dict[str, Any],
    service: Any,
    companion: Any,
    callback: CallbackQuery | None = None,
) -> bool | str:
    """Handle explicit dashboard start and revision-bound navigation only."""
    if callback and (callback.data or "").startswith("adm:"):
        parts = (callback.data or "").split(":", 2)
        if (
            len(parts) != 3
            or parts[1] != state.get("admin_revision")
            or message.message_id != state.get("admin_menu")
            or parts[2] not in state.get("admin_actions", [])
        ):
            await callback.answer("Эта кнопка устарела. Откройте /start.", show_alert=False)
            return True
        action = parts[2]
        next_state = deepcopy(state)
        if action not in {"back", "refresh", "expand", "collapse"} and not action.startswith(
            "period:"
        ):
            history = next_state.setdefault("admin_history", [])
            history.append(
                {
                    "action": next_state.get("admin_screen", "home"),
                    "args": next_state.get("admin_args", {}),
                    "period": next_state.get("admin_period", "7"),
                    "expanded": bool(next_state.get("admin_expanded")),
                }
            )
            del history[:-10]
        if action == "tools_open":
            await callback.answer()
            next_state["admin_active"] = False
            next_state["admin_revision"] = None
            next_state["admin_actions"] = []
            _replace_state(state, next_state)
            return "tools"
        if action == "qa_family":
            await callback.answer()
            next_state["admin_active"] = False
            next_state["admin_revision"] = None
            next_state["admin_actions"] = []
            _replace_state(state, next_state)
            return "qa_family"
        await present_admin(
            message, next_state, service, companion, action=action, callback=callback
        )
        _replace_state(state, next_state)
        return True
    text = message.text or ""
    words = text.split(maxsplit=1)
    if words and words[0].split("@")[0] == "/start":
        # `start=qa` is the explicit deep link back to the established exact-test UI.
        if start_payload(text) == "qa":
            return False
        next_state = deepcopy(state)
        next_state["admin_history"] = []
        await present_admin(message, next_state, service, companion)
        _replace_state(state, next_state)
        return True
    if state.get("admin_active"):
        return True
    return False
