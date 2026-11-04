from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot import router
from app.bot.router import choose_number, choose_task11
from app.math import oge11_render
from app.math.oge11 import FAMILIES, from_snapshot, verify
from app.math.oge11_scheduler import build_task11_candidate_batch
from app.persistence.repository import MemoryRepository


def _message(user_id: int, text: str) -> AsyncMock:
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = 911_000 + user_id % 1000
    message.reply_to_message = None
    return message


@pytest.mark.asyncio
async def test_disabled_task11_is_hidden_from_number_menu(monkeypatch) -> None:
    monkeypatch.setattr(router, "TASK11_ENABLED_FAMILIES", ())
    message = _message(911_001, "🧮 По номеру")

    await choose_number(message, MemoryRepository())

    labels = [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert not any(label and label.startswith("№11") for label in labels)


@pytest.mark.asyncio
async def test_enabled_task11_is_visible_in_number_menu(monkeypatch) -> None:
    monkeypatch.setattr(router, "TASK11_ENABLED_FAMILIES", FAMILIES)
    message = _message(911_004, "🧮 По номеру")

    await choose_number(message, MemoryRepository())

    labels = [
        button.text
        for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "№11 · Графики функций" in labels


@pytest.mark.asyncio
async def test_disabled_task11_cannot_issue_a_candidate(monkeypatch) -> None:
    monkeypatch.setattr(router, "TASK11_ENABLED_FAMILIES", ())
    message = _message(911_002, "№11")
    repository = MemoryRepository()

    await choose_task11(message, repository)

    message.answer_photo.assert_not_awaited()
    assert "выключены" in message.answer.await_args.args[0]
    assert await repository.task11_state(911_002) is None


def test_scheduler_emits_nothing_without_explicitly_enabled_family() -> None:
    assert build_task11_candidate_batch({}, 911_003, enabled_families=()) == []


def test_scheduler_emits_only_enabled_task11_families() -> None:
    enabled = ("OGE11-F04", "OGE11-F08")
    candidates = build_task11_candidate_batch({}, 911_005, enabled_families=enabled)

    assert candidates
    for snapshot in candidates:
        problem = from_snapshot(snapshot)
        assert problem.family_id in enabled
        assert verify(problem) == (True, "ok")


@pytest.mark.asyncio
async def test_task11_issuance_audits_only_the_selected_graph(monkeypatch) -> None:
    audits = 0
    audit_png = oge11_render.audit_png

    def counted_audit(*args, **kwargs):
        nonlocal audits
        audits += 1
        return audit_png(*args, **kwargs)

    monkeypatch.setattr(oge11_render, "audit_png", counted_audit)
    monkeypatch.setattr(router.secrets, "randbelow", lambda _: 911_005)
    monkeypatch.setattr(router, "TASK11_ENABLED_FAMILIES", ("OGE11-F04", "OGE11-F08"))
    repository = MemoryRepository()
    message = _message(911_010, "11")

    await choose_task11(message, repository)

    message.answer_photo.assert_awaited_once()
    state = await repository.task11_state(911_010)
    assert state is not None
    restored = from_snapshot(state["problem"], audit_raster=False)
    assert audits == restored.generation_attempts
    assert message.answer_photo.await_args.args[0].data == restored.png_bytes
