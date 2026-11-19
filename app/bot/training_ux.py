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


TERMINAL_RESULTS = {
    "solved": "✅ Задание решено.",
    "failed": "Попытки закончились.",
    "solution_viewed": "Вы открыли разбор.",
    "skipped": "Задание пропущено.",
}


def resumed_result(status: object, problem: Mapping[str, object]) -> str | None:
    """Show the saved outcome and any already revealed answer."""
    if not isinstance(status, str) or status not in TERMINAL_RESULTS:
        return None
    result = TERMINAL_RESULTS[status]
    if status in {"solved", "failed", "solution_viewed"} and problem.get("correct_answer"):
        result += f"\nОтвет: {problem['correct_answer']}"
    return result
