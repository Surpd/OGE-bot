"""Owner-only Telegram controller for analytics in the isolated companion bot."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from app.admin.screens import render_screen

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
    if is_period_filter and isinstance(state.get("admin_args"), dict):
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
    state["active"] = False
    state["revision"] = None
    state["actions"] = []
    is_refresh = action == "refresh"
    is_back = action == "back"
    last_args = state.get("admin_args", {})
    if is_back:
        history = state.get("admin_history", [])
        previous = history.pop() if history else state.get("admin_back")
        state["admin_history"] = history
        if isinstance(previous, dict):
            action = previous.get("action", "home")
            last_args = previous.get("args", {})
        else:
            action = "home"
    screen, args, period = _parse_action(action, state)
    if is_back and isinstance(last_args, dict):
        args = dict(last_args)
    if is_refresh and not args and isinstance(last_args, dict):
        args = dict(last_args)
    refresh = bool(state.pop("admin_refresh", False))
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
        pass
    data: Mapping[str, Any] = getattr(report, "data", {}) if report is not None else {}
    unavailable = getattr(report, "unavailable", None) if report is not None else "unavailable"
    data = dict(data)
    if unavailable:
        data["unavailable"] = unavailable
    if screen == "types":
        state["admin_type_keys"] = [str(row.get("family_id", "")) for row in data.get("rows", [])]
    username = getattr(getattr(companion, "identity", None), "username", None)
    if not username and getattr(companion, "bot", None):
        username = getattr(companion.bot, "username", None)
    tools_url = f"https://t.me/{username}?start=qa" if username else None
    text, markup = render_screen(
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
    )
    state.update(
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
    if callback is None:
        sent = await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        state["admin_menu"] = sent.message_id
        return
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        state["admin_menu"] = message.message_id
    except TelegramBadRequest:
        sent = await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        state["admin_menu"] = sent.message_id


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
        if action not in {"back", "refresh"} and not action.startswith("period:"):
            history = state.setdefault("admin_history", [])
            history.append(
                {
                    "action": state.get("admin_screen", "home"),
                    "args": state.get("admin_args", {}),
                    "period": state.get("admin_period", "7"),
                }
            )
            del history[:-10]
        if action == "tools_open":
            await callback.answer()
            state["admin_active"] = False
            state["admin_revision"] = None
            state["admin_actions"] = []
            return "tools"
        if action == "qa_family":
            await callback.answer()
            state["admin_active"] = False
            state["admin_revision"] = None
            state["admin_actions"] = []
            return "qa_family"
        await present_admin(message, state, service, companion, action=action, callback=callback)
        return True
    text = message.text or ""
    words = text.split(maxsplit=1)
    if words and words[0].split("@")[0] == "/start":
        # `start=qa` is the explicit deep link back to the established exact-test UI.
        if start_payload(text) == "qa":
            return False
        state["admin_history"] = []
        await present_admin(message, state, service, companion)
        return True
    if state.get("admin_active"):
        return True
    return False
