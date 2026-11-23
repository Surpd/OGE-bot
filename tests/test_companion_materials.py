"""The combined candidate must deliver #106 materials through #107's exact QA desk."""

import copy

from aiogram.exceptions import TelegramNetworkError
from test_companion_qa import harness as harness

from app.companion.catalog import fixture
from app.math.scenario_engine import ScenarioSnapshot
from app.math.scenarios.mobile_photos import scenario_photos

__all__ = ["harness"]


async def test_exact_stove_catalogue_precedes_question_and_keeps_private_controls(harness):
    h = harness
    await h.message("/start")
    await h.click("fixture:0")
    state = await h.state()
    original = copy.deepcopy(state["card"])
    snapshot = ScenarioSnapshot.from_snapshot(original["scenario"])
    expected_catalogue = scenario_photos(snapshot)[0]
    assert snapshot.questions[0].condition.endswith("23, 12, 20.")
    calls = h.transport.calls
    catalogue_indices = [
        i
        for i, c in enumerate(calls)
        if c.__api_method__ == "sendPhoto" and getattr(c.photo, "data", None) == expected_catalogue
    ]
    assert len(catalogue_indices) == 1
    prompt = h.transport.messages[state["replay"]["prompt_message_id"]]
    assert snapshot.questions[0].condition in prompt.text
    assert catalogue_indices[0] < len(calls) - 1
    assert all(
        b.callback_data.startswith("qa:")
        for row in prompt.reply_markup.inline_keyboard
        for b in row
    )
    old = h.button("repeat")
    await h.click("hint")
    assert (await h.state())["replay"]["prompt_message_id"] == prompt.message_id
    await h.click(saved=old)  # The previous controls revision is stale.
    assert (await h.state())["source_id"] == state["source_id"]
    await h.click("repeat")
    assert (await h.state())["card"] == original
    assert (
        sum(
            c.__api_method__ == "sendPhoto" and getattr(c.photo, "data", None) == expected_catalogue
            for c in calls
        )
        == 2
    )


async def test_missing_material_blocks_qa_question_and_explicit_retry_is_exact(
    harness, monkeypatch
):
    h = harness
    await h.message("/start")
    send = h.transport.make_request
    failed = []

    async def fail_catalogue(bot, method, timeout=None):  # noqa: ASYNC109
        if method.__api_method__ == "sendPhoto":
            failed.append(method)
            raise TelegramNetworkError(method=method, message="synthetic material timeout")
        return await send(bot, method, timeout)

    monkeypatch.setattr(h.transport, "make_request", fail_catalogue)
    old = await h.click("fixture:0")
    state = await h.state()
    assert state["card"] == fixture(0)
    assert state["replay"]["prompt_message_id"] is None
    assert state["card"]["snapshot"]["condition"] not in h.text()
    assert len(failed) == 1
    await h.click(saved=old)
    assert len(failed) == 1
    monkeypatch.setattr(h.transport, "make_request", send)
    await h.message("/qa")
    await h.click("repeat")
    recovered = await h.state()
    assert recovered["card"] == state["card"]
    assert recovered["replay"]["attempt_count"] == 0
    assert recovered["card"]["snapshot"]["condition"] in h.text()
