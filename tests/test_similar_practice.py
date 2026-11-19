from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.bot.navigation import prepare_navigation_markup
from app.bot.progress import encode_record_ref, progress_navigation
from app.bot.similar_practice import _choices
from app.math.generator import generate
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import training_insights


@pytest.mark.asyncio
async def test_similar_is_new_ordinary_work_and_requires_consent_to_replace_active_question():
    store = MemoryRepository()
    user = 6719
    snapshot = generate("OGE06-F001-ADD", 77_661).to_snapshot()
    problem_id = str(snapshot["problem_id"])
    await store.ensure_task6_session(user)
    await store.advance_task6_problem(user, None, [snapshot])
    await store.save_user_state(user, "task6")
    assert await store.task6_attempt(user, problem_id, "0", False, 20)
    before = await training_insights(store, user)
    token = encode_record_ref(f"o:{problem_id}")

    message = AsyncMock()
    message.from_user = SimpleNamespace(id=user, is_bot=False)
    message.message_id = 30
    message.answer.return_value.message_id = 31
    await progress_navigation(message, store, user, f"similar:{token}")
    assert "незавершённое" in message.answer.await_args.args[0]
    assert await training_insights(store, user) == before

    await progress_navigation(message, store, user, f"similar:{token}:y")
    current = await store.task6_state(user)
    assert current is not None
    issued = current["problem"]
    assert issued["family_id"] == snapshot["family_id"]
    assert issued["problem_id"] != problem_id
    assert issued["fingerprint"] != snapshot["fingerprint"]
    assert store.issued_history[user][problem_id] == snapshot
    assert store.outcomes[user][problem_id] == "issued"
    assert await store.user_state(user) == "task6"
    after = await training_insights(store, user)
    assert after["total"]["issued"] == before["total"]["issued"] + 1
    assert after["total"]["attempts"] == before["total"]["attempts"]
    assert after["total"]["skipped"] == before["total"]["skipped"]
    await progress_navigation(message, store, user + 1, f"similar:{token}:y")
    assert (await training_insights(store, user + 1))["total"]["issued"] == 0


def test_similar_confirmation_with_scenario_reference_fits_callback_limit():
    token = encode_record_ref(f"s:{UUID(int=42)}:5")
    markup = prepare_navigation_markup(_choices(token, active=True))
    assert all(
        len(button.callback_data.encode()) <= 64
        for row in markup.inline_keyboard for button in row
    )
