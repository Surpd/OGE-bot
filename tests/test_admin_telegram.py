from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.types import Update
from test_inline_dispatcher_postgres import TelegramSession

from app.admin.screens import render_screen
from app.admin.telegram import _parse_action, handle_admin_update, present_admin
from app.companion.catalog import generate
from app.companion.middleware import CompanionMiddleware, allowed_payload
from app.config import Settings
from app.persistence.repository import MemoryRepository


class Service:
    def __init__(self, report=None, fail=False):
        self.report = report or SimpleNamespace(
            data={"registered": 8, "active": 3}, unavailable=None, window=None
        )
        self.fail = fail
        self.calls = []

    async def load(self, view, period, **kwargs):
        self.calls.append((view, period, kwargs))
        if self.fail:
            raise TimeoutError
        return self.report


class Msg:
    def __init__(self, message_id=55):
        self.message_id = message_id
        self.photo = None
        self.bot = None
        self.sent = []
        self.edited = []

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return SimpleNamespace(message_id=99)

    async def answer_photo(self, photo, **kwargs):
        self.sent.append((photo, kwargs))
        return SimpleNamespace(message_id=99)

    async def edit_text(self, text, **kwargs):
        self.edited.append((text, kwargs))


class Callback:
    def __init__(self, data, message, user_id=42):
        self.data, self.message = data, message
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


def test_admin_owner_gate_requires_private_owner_chat():
    payload = {
        "message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "/start"}
    }
    assert allowed_payload(payload, 42)
    assert not allowed_payload(payload, 43)
    payload["message"]["chat"]["type"] = "group"
    assert not allowed_payload(payload, 42)


def test_report_screens_have_compact_actual_telegram_navigation():
    text, keyboard = render_screen("home", {"registered": 5, "active": 2}, revision="abc")
    assert "Аккаунтов всего  <b>5</b>" in text
    assert "Занимались  <b>2</b>" in text
    assert "<b>bop Admin · Обзор</b>" in text
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "adm:abc:usage" in callbacks
    assert "adm:abc:tasks" in callbacks
    assert "adm:abc:period:7" in callbacks
    assert max(len(callback.encode("utf-8")) for callback in callbacks) <= 64


def test_unavailable_screen_does_not_present_missing_metrics_as_zeroes():
    text, _ = render_screen("home", {"unavailable": "unconfigured"})
    assert "Подключение к аналитике отсутствует" in text
    assert "Занимались" not in text


def test_today_hides_multi_day_metric_and_attention_list_is_capped():
    text, _ = render_screen(
        "home",
        {"registered": 6, "active": 2, "repeat_days": 1, "unknown_cost": 7, "errors": 3},
        period="today",
        companion_status="unavailable",
    )
    assert "Занимались в разные дни" not in text
    assert text.count("Запросы с неизвестной стоимостью") == 1
    assert len(text.split("<b>Требует внимания</b>\n", 1)[1].splitlines()) == 3


def test_report_labels_localize_written_and_task_detail():
    written, _ = render_screen("written", {"issued": 2, "graded": 1})
    assert "Заданий выдано  <b>2</b>" in written and "С оценкой  <b>1</b>" in written
    task, _ = render_screen("task", {"users": 3, "hinted": 1, "hint_known": 2})
    assert "Ученики  <b>3</b>" in task and "Брали подсказку  <b>1 из 2</b>" in task
    assert "first_correct" not in task


def test_deep_report_routes_keep_filters_and_expose_family_tool_action():
    type_text, type_keyboard = render_screen(
        "types",
        {"rows": [{"family_id": "OGE12-R001", "answered": 11}], "more": True},
        revision="r",
        number=12,
        page=1,
        sort="help",
    )
    type_callbacks = [
        button.callback_data for row in type_keyboard.inline_keyboard for button in row
    ]
    assert any(value and value.endswith(":types:12:2:help") for value in type_callbacks)
    assert "adm:r:task:12" in type_callbacks
    _, task_keyboard = render_screen(
        "task", {"users": 1}, revision="r", number=12, family_id="OGE12-R001"
    )
    task_callbacks = [
        button.callback_data for row in task_keyboard.inline_keyboard for button in row
    ]
    assert "adm:r:qa_family" in task_callbacks
    _, written_keyboard = render_screen("written", {"rows": [], "more": True}, revision="r", page=0)
    written_callbacks = [
        button.callback_data for row in written_keyboard.inline_keyboard for button in row
    ]
    assert "adm:r:written:0:1" in written_callbacks
    _, replay_keyboard = render_screen("replays", {"rows": [], "more": True}, revision="r")
    assert any(
        button.callback_data == "adm:r:replays:1"
        for row in replay_keyboard.inline_keyboard
        for button in row
    )


def test_long_family_ids_do_not_overflow_callback_data_and_task_list_is_paginated():
    text, keyboard = render_screen(
        "types",
        {"rows": [{"family_id": "x" * 180, "answered": 10, "solved": 4}], "more": True},
        revision="a" * 10,
        number=19,
    )
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert max(len(value.encode("utf-8")) for value in callbacks) <= 64
    assert "x" * 180 not in callbacks
    task_text, task_keyboard = render_screen(
        "tasks", {"rows": [{"number": n, "answered": 1} for n in range(1, 20)]}, page=1
    )
    task_callbacks = [
        button.callback_data for row in task_keyboard.inline_keyboard for button in row
    ]
    assert "<b>№11</b>" in task_text and "<b>№19</b>" in task_text
    assert "<b>№1</b>" not in task_text
    assert any(value.endswith(":tasks:0") for value in task_callbacks)


def test_callback_parser_keeps_period_and_opaque_learner_key():
    state = {}
    screen, args, period = _parse_action("period:28", state)
    assert (screen, period, state["admin_period"]) == ("home", "28", "28")
    screen, args, _ = _parse_action("learner:5a6e9b3d-opaque", state)
    assert (screen, args["key"]) == ("learner", "5a6e9b3d-opaque")


@pytest.mark.asyncio
async def test_old_admin_callback_is_rejected_without_loading_report():
    message = Msg()
    callback = Callback("adm:old:usage", message)
    service = Service()
    state = {"admin_revision": "new", "admin_menu": 55, "admin_actions": ["usage"]}
    assert await handle_admin_update(message, state, service, SimpleNamespace(), callback)
    assert callback.answers and "устарела" in callback.answers[0][0][0]
    assert not service.calls


@pytest.mark.asyncio
async def test_degraded_report_is_rendered_as_safe_unavailable_state():
    service = Service(fail=True)
    message = Msg()
    state = {}
    companion = SimpleNamespace(status="ready", sha="a" * 40, identity=None, bot=None)
    await present_admin(message, state, service, companion)
    text, _ = message.sent[0]
    assert "Аналитика временно недоступна" in text
    assert "TimeoutError" not in text
    assert state["admin_menu"] == 99


@pytest.mark.asyncio
async def test_current_admin_callback_refreshes_and_rotates_revision():
    service = Service()
    message = Msg()
    callback = Callback("adm:r1:usage", message)
    state = {"admin_revision": "r1", "admin_menu": 55, "admin_actions": ["usage"]}
    companion = SimpleNamespace(status="ready", sha="local", identity=None, bot=None)
    assert await handle_admin_update(message, state, service, companion, callback)
    assert service.calls[0][:2] == ("usage", "7")
    assert state["admin_revision"] != "r1"
    assert message.sent[0][1]["parse_mode"] == "HTML"
    assert state["admin_menu"] == 99


@pytest.mark.asyncio
async def test_back_restores_previous_number_sort_and_period():
    service = Service()
    message = Msg()
    callback = Callback("adm:r2:back", message)
    state = {
        "admin_revision": "r2",
        "admin_menu": 55,
        "admin_actions": ["back"],
        "admin_screen": "task",
        "admin_args": {"number": 12, "key": "OGE12-R001"},
        "admin_period": "28",
        "admin_history": [
            {
                "action": "types",
                "args": {"number": 12, "page": 1, "sort": "help"},
                "period": "7",
                "expanded": True,
            }
        ],
    }
    await handle_admin_update(message, state, service, SimpleNamespace(), callback)
    assert service.calls[0][:2] == ("types", "28")
    assert service.calls[0][2]["number"] == 12
    assert service.calls[0][2]["page"] == 1
    assert service.calls[0][2]["sort"] == "help"
    assert state["admin_expanded"] is True


@pytest.mark.asyncio
async def test_owner_photo_without_caption_does_not_break_admin_command_detection():
    bot = Bot("123456:TEST", session=TelegramSession())
    update = Update.model_validate(
        {
            "update_id": 7,
            "message": {
                "message_id": 8,
                "date": int(datetime.now(UTC).timestamp()),
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
                "photo": [
                    {"file_id": "not-real", "file_unique_id": "not-real", "width": 1, "height": 1}
                ],
            },
        }
    ).as_(bot)
    middleware = CompanionMiddleware(
        Settings(_env_file=None, telegram_test_owner_ids="42"),
        frozenset({42}),
        "a" * 40,
        admin_service=Service(),
    )
    called = []

    async def handler(event, data):
        called.append(event.message.photo[0].file_id)
        return "handled"

    result = await middleware(handler, update, {"repository": MemoryRepository()})
    assert result == "handled"
    assert called == ["companion-synthetic"]


def test_admin_exact_story_family_launch_uses_the_requested_public_type():
    card = generate(1, "TYRES-TABLE-EXTREME", seed=0)
    assert card["scenario"]["story_code"] == "TYRES"
    assert card["snapshot"]["family_id"] == "TYRES-TABLE-EXTREME"


def test_admin_learner_card_formats_database_timestamps_in_moscow_time():
    last_activity = datetime(2026, 11, 27, 23, 15, tzinfo=UTC)
    text, _ = render_screen("learner", {"found": True, "last_activity": last_activity})
    assert "28.11 02:15 МСК" in text
