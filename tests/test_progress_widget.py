import json

import pytest

from app.bot.progress_widget import (
    WIDGET_HTML,
    handle_widget_query,
    overview_data,
    widget_response,
    widget_size,
)
from app.bot.widget_api import AnswerWidgetQuery, SendWidget
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import summarize


def test_widget_html_stays_within_official_size_limits_and_is_self_contained():
    html_size, compressed_size = widget_size()
    assert html_size <= 32768
    assert compressed_size <= 4096
    assert "https://" not in WIDGET_HTML
    assert "--tg-theme-bg-color" in WIDGET_HTML
    assert "max-width:560px" in WIDGET_HTML


def test_widget_overview_uses_only_defined_completed_result_metrics():
    data = summarize([
        {"number": 9, "family_id": "OGE09-F001", "outcome": "solved",
         "attempt_records": [{"attempt_no": 1, "is_correct": True, "used_hint": False}]},
        {"number": 9, "family_id": "OGE09-F001", "outcome": "failed",
         "attempt_records": [{"attempt_no": 1, "is_correct": False}]},
        {"number": 12, "family_id": "OGE12-F001", "outcome": "issued"},
    ])
    overview = json.loads(overview_data(data))
    assert overview["p"]["c"] == 2
    assert overview["p"]["u"] == 1
    assert overview["p"]["e"] == 1
    assert "2 из 5" in overview["p"]["r"]


@pytest.mark.asyncio
async def test_widget_uses_private_telegram_identity_and_bounded_queries():
    repository = MemoryRepository()
    repository.issued9[42] = {"p1": {"family_id": "OGE09-F001", "condition": "2 + 2"}}
    repository.outcomes9[42] = {"p1": "solved"}
    repository.attempts9[42] = [
        {"problem_id": "p1", "attempt_no": 1, "is_correct": True, "used_hint": False}
    ]
    calls = []

    async def bot(method, **kwargs):
        calls.append(method)
        return True

    base = {
        "id": "q-1",
        "from": {"id": 42},
        "chat": {"id": 42, "type": "private"},
        "type": {"type": "data"},
        "data": "refresh",
    }
    await handle_widget_query(bot, repository, base)
    assert len(calls) == 1 and isinstance(calls[0], AnswerWidgetQuery)
    assert json.loads(calls[0].data)["p"]["c"] == 1

    calls.clear()
    await handle_widget_query(bot, repository, {**base, "id": "q-2",
                                                  "chat": {"id": 43, "type": "private"}})
    assert len(calls) == 1 and calls[0].data == '{"tab":"err"}'

    calls.clear()
    await handle_widget_query(bot, repository, {**base, "id": "q-3", "data": "x" * 65})
    assert len(calls) == 1 and calls[0].data == '{"tab":"err"}'

    history = await widget_response(repository, 42, "tab:h")
    assert len(history.encode("utf-8")) <= 1024
    assert "c" not in json.loads(history)["r"][0]
    empty = await widget_response(repository, 43, "tab:h")
    assert json.loads(empty)["r"] == []


def test_bot_api_10_4_adapters_use_official_method_names():
    send = SendWidget(chat_id=42, html=WIDGET_HTML, is_shared=False)
    answer = AnswerWidgetQuery(widget_query_id="query", data="{}")
    assert send.__api_method__ == "sendWidget"
    assert answer.__api_method__ == "answerWidgetQuery"
    assert send.chat_id == 42 and send.is_shared is False
