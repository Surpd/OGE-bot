import base64
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import BufferedInputFile, Chat, Message, User

from app.bot import router
from app.bot.presentation import MathDeliveryUncertain, send_photo
from app.math import oge16_scheduler
from app.math.oge16_circles import (
    FAMILIES,
    from_snapshot,
    generate,
)
from app.persistence.repository import MemoryRepository


@pytest.fixture(autouse=True)
def enabled_training(monkeypatch):
    monkeypatch.setattr(oge16_scheduler, "ENABLED_FAMILIES", FAMILIES)


def message(text="", mid=100):
    incoming = AsyncMock()
    incoming.from_user = User(id=42, is_bot=False, first_name="Student")
    incoming.message_id = mid
    incoming.text = text
    incoming.reply_to_message = None
    incoming.answer.return_value.message_id = mid + 1
    incoming.answer_photo.return_value.message_id = mid + 1
    return incoming


async def test_default_menu_and_entry_offer_task16_with_a_real_png():
    repo = MemoryRepository()
    incoming = message()
    await router.choose_number(incoming, repo, page=1)
    labels = [
        b.text
        for row in incoming.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert any(text.startswith("№16") for text in labels)
    task_message = message(mid=102)
    await router.choose_task16(task_message, repo)
    saved = await repo.task16_state(42)
    assert saved is not None
    snapshot = saved["problem"]
    assert snapshot["family_id"] in FAMILIES
    assert snapshot["figure"]["renderer_version"] == "oge16-pillow-2"
    assert task_message.answer_photo.await_args.kwargs["caption"] == (
        f"<b>Задание №16</b>\n\n{snapshot['condition']}"
    )
    assert task_message.answer_photo.await_args.args[0].data == from_snapshot(snapshot).png


def test_default_task16_scheduler_cycles_all_families_and_finite_pools():
    from app.math.oge16_scheduler import build_task16_candidate_batch

    state: dict[str, object] = {}
    visited = set()
    for seed in range(len(FAMILIES)):
        snapshot = build_task16_candidate_batch(state, seed)[0]
        visited.add(snapshot["family_id"])
        state = {
            "family_queue": snapshot["_family_queue_after"],
            "last_family_id": snapshot["_last_family_after"],
            "recent_fingerprints": [snapshot["fingerprint"]],
        }
    assert visited == set(FAMILIES)

    from app.math.oge16_scheduler import finite_pool

    family = "OGE16-C03"
    exhausted = [fp for fp, _ in finite_pool(family)]
    recycled = build_task16_candidate_batch(
        {"selected_family_id": family, "recent_fingerprints": exhausted}, 55
    )[0]
    assert recycled["family_id"] == family
    assert set(recycled["_finite_cycle_fingerprints"]) == set(exhausted)


async def test_default_telegram_route_answers_and_advances_all_enabled_families():
    repo = MemoryRepository()
    opened = message()
    await router.choose_task16(opened, repo)
    visited = set()
    current_prompt_id = 101
    for _ in FAMILIES:
        saved = await repo.task16_state(42)
        snapshot = saved["problem"]
        family = snapshot["family_id"]
        visited.add(family)
        assert opened.answer_photo.await_args.args[0].data == from_snapshot(snapshot).png
        answer_message = message(snapshot["correct_answer"], current_prompt_id + 1)
        await router.task16_answer(answer_message, repo)
        assert (await repo.task16_state(42))["state"]["status"] == "solved"
        control_id = answer_message.message_id + 1
        callback = AsyncMock()
        callback.data = f"t16:next:{snapshot['problem_id']}"
        callback.from_user = User(id=42, is_bot=False, first_name="Student")
        callback.message = AsyncMock()
        callback.message.message_id = control_id
        callback.message.answer_photo.return_value.message_id = control_id + 1
        callback.message.answer.return_value.message_id = control_id + 1
        await router.task16_callback(callback, repo)
        current_prompt_id = control_id + 1
        opened = callback.message
    assert visited == set(FAMILIES)


@pytest.mark.parametrize("family", (FAMILIES[0], FAMILIES[1]))
async def test_same_png_and_counts_on_resume_and_corruption_fails_closed(monkeypatch, family):
    monkeypatch.setattr(oge16_scheduler, "ENABLED_FAMILIES", (family,))
    repo = MemoryRepository()
    first = message()
    await router.choose_task16(first, repo)
    saved = await repo.task16_state(42)
    original = from_snapshot(saved["problem"])
    assert first.answer_photo.await_args.args[0].data == original.png
    assert saved["state"]["problem_prompt_message_id"] == 101
    await router.task16_answer(message("0", 102), repo)
    assert (await repo.task16_state(42))["state"]["attempts"] == 1
    await repo.save_user_state(42, "main_menu")
    resumed = message(mid=104)
    await router.continue_session(resumed, repo)
    assert resumed.answer_photo.await_args.args[0].data == original.png
    assert (await repo.task16_state(42))["state"]["attempts"] == 1
    saved["problem"]["figure"]["sha256"] = "bad"
    broken = message(mid=106)
    assert not await router._send_task16_problem(broken, repo, action="resume")
    broken.answer_photo.assert_not_awaited()
    await router.task16_answer(message("4", 108), repo)
    assert (await repo.task16_state(42))["state"]["attempts"] == 1


@pytest.mark.parametrize("family", (FAMILIES[0], FAMILIES[1]))
async def test_resume_restores_exact_saved_png(family):
    problem = generate(family, 42)
    snapshot = problem.to_snapshot()
    assert snapshot["figure"]["renderer_version"] in {"oge16-pillow-1", "oge16-pillow-2"}
    repo = MemoryRepository()
    await repo.ensure_task16_session(42)
    await repo.advance_task16_problem(42, None, [snapshot])
    await repo.save_user_state(42, "task16")
    await repo.set_task16_condition_message(42, snapshot["problem_id"], 101)

    resumed = message(mid=102)
    await router.continue_session(resumed, repo)

    assert resumed.answer_photo.await_args.args[0].data == problem.png


@pytest.mark.parametrize(
    "display,error",
    (
        ("auto", None),
        ("png", None),
        ("auto", TelegramBadRequest),
        ("auto", TelegramNetworkError),
    ),
)
async def test_real_png_transport_media_fallback_and_ambiguous_timeout(display, error):
    bot = Bot("123456:TEST")
    sent = Message(message_id=91, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    method = SendRichMessage(chat_id=42, rich_message={"html": "test"})
    reason = "Bad Request: can't parse entities: unsupported start tag"
    effect = error(method=method, message=reason) if error else None
    bot.send_rich_message = AsyncMock(return_value=sent, side_effect=effect)
    bot.send_photo = AsyncMock(return_value=sent)
    repo = MemoryRepository()
    await repo.set_math_display(42, display)
    incoming = Message(
        message_id=19,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Student"),
    ).as_(bot)
    problem = generate(FAMILIES[0], 42)
    photo = BufferedInputFile(problem.png, "oge16.png")
    # Exercise the existing rich media path with the same exact saved diagram.
    kwargs = {"caption": f"Задание №16\n{problem.to_snapshot()['condition']}"}
    try:
        if error is TelegramNetworkError:
            with pytest.raises(MathDeliveryUncertain) as uncertain:
                await send_photo(incoming, repo, photo, **kwargs)
            assert isinstance(uncertain.value.__cause__, TelegramNetworkError)
            bot.send_photo.assert_not_awaited()
        else:
            result = await send_photo(incoming, repo, photo, **kwargs)
            assert result.message_id == 91
            if display == "auto" and error is None:
                payload = bot.send_rich_message.await_args.kwargs
                assert payload["rich_message"].media[0].media.media.data == problem.png
            else:
                bot.send_photo.assert_awaited_once()
                assert bot.send_photo.await_args.kwargs["photo"].data.startswith(b"\x89PNG")
        assert base64.b64decode(problem.to_snapshot()["figure"]["png_base64"]) == problem.png
    finally:
        await bot.session.close()


def test_task16_duplicate_webhook_is_processed_once(monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "oge16-test-secret")
    monkeypatch.setattr(oge16_scheduler, "ENABLED_FAMILIES", FAMILIES)
    get_settings.cache_clear()
    repo = MemoryRepository()
    snapshot = generate(FAMILIES[0], 0).to_snapshot()

    async def prepare():
        await repo.ensure_task16_session(42)
        await repo.advance_task16_problem(42, None, [snapshot])
        await repo.save_user_state(42, "task16")
        await repo.set_task16_condition_message(42, snapshot["problem_id"], 100)

    asyncio.run(prepare())
    bot = Bot("123456:TEST")
    sent = Message(message_id=102, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.session.make_request = AsyncMock(return_value=sent)
    app = create_app(repository=repo, bot=bot, run_schema_migrations=False)
    payload = {
        "update_id": 16001,
        "message": {
            "message_id": 101,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Student"},
            "text": snapshot["correct_answer"],
        },
    }
    try:
        with TestClient(app) as client:
            for _ in range(2):
                response = client.post(
                    "/telegram/webhook",
                    json=payload,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "oge16-test-secret"},
                )
                assert response.status_code == 200
        assert repo.updates[123456, 16001] == "processed"
        assert len(repo.attempts16[42]) == 1
        assert repo.outcomes16[42][snapshot["problem_id"]] == "solved"
        bot.session.make_request.assert_awaited_once()
    finally:
        get_settings.cache_clear()


async def test_finite_cycle_restarts_without_polluting_task18_state():
    from app.math.oge16_scheduler import build_task16_candidate_batch, finite_pool

    repo = MemoryRepository()
    first = message()
    await repo.set_training_family(42, 16, "OGE16-C03")
    await router.choose_task16(first, repo)
    old = await repo.task16_state(42)
    assert repo.training18 == repo.issued18 == {}
    assert len(repo.issued16[42]) == 1
    old_pid = old["problem"]["problem_id"]
    old["state"]["recent_fingerprints"] = [fp for fp, _ in finite_pool("OGE16-C03")]
    batch = build_task16_candidate_batch({**old["state"], "selected_family_id": "OGE16-C03"}, 99)
    issued = await repo.advance_task16_problem(42, old_pid, batch, "task16", 101, True)
    assert issued["_transitioned"] is True
    assert issued["problem_id"] != old_pid
    current = await repo.task16_state(42)
    assert len(current["state"]["recent_fingerprints"]) == 1
    assert "_finite_cycle_fingerprints" not in current["problem"]
    assert repo.training18 == repo.issued18 == {}
    assert (await repo.task16_progress(42))["issued"] == 2


async def test_public_gate_hides_task16_and_rejects_direct_entry(monkeypatch):
    monkeypatch.setattr(oge16_scheduler, "ENABLED_FAMILIES", ())
    repo = MemoryRepository()
    outgoing = message()
    await router.choose_number(outgoing, repo, page=1)
    labels = [
        b.text
        for row in outgoing.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert not any(label.startswith("№16") for label in labels)
    await router.choose_task16(outgoing, repo)
    outgoing.answer_photo.assert_not_awaited()
    assert await repo.task16_state(42) is None
