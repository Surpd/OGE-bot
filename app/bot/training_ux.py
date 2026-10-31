"""Shared input rules for Telegram training flows."""

from collections.abc import Mapping

from aiogram.types import Message


def matches_current_condition(message: Message, state: Mapping[str, object]) -> bool:
    """Accept a plain chat answer or a reply to the current condition only."""
    condition_id = state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
    if type(condition_id) is not int or type(message.message_id) is not int:
        return False
    if message.message_id <= condition_id:
        return False
    reply = message.reply_to_message
    return reply is None or getattr(reply, "message_id", None) == condition_id
