from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adaptive.engine import Stage, State
from app.bot import adaptive
from app.bot.progress import _recommendation, _summary_action
from app.bot.progress_image import _recommendation as image_tip

GAP = "OGE09-L1"
WEAK = "OGE13-L01"
RECENT = "OGE06-F001-ADD"


@pytest.fixture
def profile(monkeypatch):
    at = datetime(2026, 11, 25, tzinfo=UTC)
    numbers = {9: {"correct": 8, "answered_tasks": 10}, 13: {"correct": 2, "answered_tasks": 10}}
    history = [
        (9, GAP, State(stage=Stage.GAP, opened=1), at - timedelta(days=1)),
        (6, RECENT, State(stage=Stage.PRACTICE, practice=1), at),
    ]
    insights = {"numbers": numbers}
    monkeypatch.setattr(adaptive, "catalog", lambda: {GAP: 9, WEAK: 13, RECENT: 6})
    return history, insights


async def test_progress_and_summary_match_personal_plan(monkeypatch, profile):
    history, insights = profile
    learner = 42
    monkeypatch.setattr(adaptive, "get_settings",
                        lambda: SimpleNamespace(oge_adaptive_enabled=True))
    repository = SimpleNamespace(
        personal_enabled=AsyncMock(return_value=True), save_user_state=AsyncMock(),
        last_training_mode=AsyncMock(return_value=None),
    )
    store = SimpleNamespace(
        learner=learner, current=AsyncMock(return_value=None),
        excluded_for_learner=AsyncMock(return_value=[]),
        totals=AsyncMock(return_value={"issued": 5, "completed": 5, "solved": 2, "independent": 1}),
        summary_deltas=AsyncMock(return_value=[]),
        difficulties=AsyncMock(return_value={GAP: 2}),
    )
    monkeypatch.setattr(adaptive, "Session", lambda *_: store)
    monkeypatch.setattr(adaptive, "_learner_inputs", AsyncMock(return_value=(history, insights)))
    sent = AsyncMock()
    monkeypatch.setattr(adaptive, "send_text", sent)
    message = SimpleNamespace(message_id=1, from_user=SimpleNamespace(id=learner))

    plan = adaptive._mode_plan("personal", learner, history, insights)
    await adaptive.progress_target(repository, learner, insights)
    await adaptive.trainings(message, repository)
    hub = sent.await_args
    await adaptive.completion(message, repository, store, {"id": "done"}, "Тренировка завершена!")
    summary = sent.await_args
    label, route = _summary_action(insights)
    assert plan[0] == GAP and route == f"train:family:{GAP}"
    assert _recommendation(insights) == image_tip(insights) == insights["personal_tip"]
    assert hub.args[2] == "Тренировки"
    assert not any(
        b.callback_data == route for row in hub.kwargs["reply_markup"].inline_keyboard for b in row
    )
    assert insights["personal_tip"] in summary.args[2]
    assert (label, route) in [
        (b.text, b.callback_data)
        for row in summary.kwargs["reply_markup"].inline_keyboard for b in row
    ]


def test_mixed_plan_ignores_personal_inputs_on_start_and_reselection(profile):
    history, insights = profile
    assert adaptive._mode_plan("mixed", 42, history, insights, seed="acceptance") == (
        adaptive._mode_plan("mixed", 42, [], {}, seed="acceptance")
    )
    context = {"seed": "acceptance", "prefix": [RECENT], "excluded": [GAP]}
    assert adaptive._select("mixed", 42, history, insights, **context) == (
        adaptive._select("mixed", 42, [], {}, **context)
    )


async def test_all_independent_answers_do_not_invent_a_problem(monkeypatch, profile):
    history, _ = profile
    repository = SimpleNamespace(personal_enabled=AsyncMock(return_value=True),
                                 save_user_state=AsyncMock())
    store = SimpleNamespace(
        learner=42, excluded_for_learner=AsyncMock(return_value=[]),
        totals=AsyncMock(return_value={"completed": 5, "issued": 5, "solved": 5, "independent": 5}),
        summary_deltas=AsyncMock(return_value=[]), difficulties=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(adaptive, "_learner_inputs",
                        AsyncMock(return_value=(history[1:], {"numbers": {}})))
    sent = AsyncMock()
    monkeypatch.setattr(adaptive, "send_text", sent)
    await adaptive.completion(object(), repository, store, {"id": "done"}, "Тренировка завершена!")
    assert "Решено верно: 5 из 5" in sent.await_args.args[2]
    assert "Самостоятельно: 5 из 5" in sent.await_args.args[2]
    assert "Что потренировать дальше" not in sent.await_args.args[2]
    assert [button.callback_data
            for row in sent.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row] == ["train:personal", "train:progress", "nav:main"]


def test_number_focus_links_to_practice_and_session_help_outranks_recent_success(profile):
    history, insights = profile
    ranked = adaptive._select("personal", 42, [], insights, recommendations_only=True, size=1)
    assert adaptive._recommendation_action(ranked.reasons[0])[1] == "train:number:13"
    ranked = adaptive._select(
        "personal", 42, history[1:], {}, recommendations_only=True, size=1, difficulties={GAP: 1},
    )
    assert ranked.reasons[0].family == GAP
