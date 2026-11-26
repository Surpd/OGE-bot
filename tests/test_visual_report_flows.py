import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, User

from app.adaptive.planner import PlanResult, SelectionReason
from app.bot import adaptive, mixed_training, progress
from app.config import get_settings
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import summarize


def _message(message_id, **kwargs):
    return Message(
        message_id=message_id, date=datetime.now(UTC), chat=Chat(id=42, type="private"), **kwargs,
    )


async def test_number_progress_keeps_overview_anchor_and_real_stats(monkeypatch):
    insights = summarize([])
    insights["numbers"][9].update(correct=4, answered_tasks=6, unknown_assistance=2)
    insights.update(independent_count=1)
    monkeypatch.setattr(progress, "visual_enabled", lambda *_: True)
    monkeypatch.setattr(progress, "training_insights", AsyncMock(return_value=insights))
    monkeypatch.setattr(progress, "_include_family_states", AsyncMock())
    capture = AsyncMock(return_value=_message(11))
    monkeypatch.setattr("app.bot.presentation.send_text", capture)
    send_overview = AsyncMock(return_value=True)
    monkeypatch.setattr("app.bot.progress_image.send_progress_image", send_overview)
    delete = AsyncMock()
    monkeypatch.setattr(Message, "delete", delete)
    photo = PhotoSize(file_id="photo", file_unique_id="photo", width=600, height=600)
    overview = _message(9, photo=[photo])
    picker = _message(10, reply_to_message=overview)
    repository = MemoryRepository()

    await progress.progress_navigation(picker, repository, 42, "number:9")
    card = capture.await_args.kwargs["visual"]
    assert [(m.value, m.label) for m in card.metrics] == [
        ("4/6", "Верно"), ("67%", "Успешность"), ("1", "Новых самостоятельно"),
    ]
    assert any("неизвестно: 2" in entry.label for entry in card.sections[0].entries)
    kwargs = capture.await_args.kwargs
    assert kwargs["reply_parameters"].message_id == overview.message_id
    actions = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert "progress:numhist:9:0" in actions and "progress:details" in actions
    assert "Решено правильно: 4 из 6" in capture.await_args.args[2]
    delete.assert_awaited_once()

    detail = _message(11, photo=[photo], reply_to_message=overview)
    await progress.progress_navigation(detail, repository, 42, "summary")
    assert send_overview.await_args.args[0] == overview
    assert send_overview.await_args.kwargs["edit_existing"] is True


async def test_checkpoint_keeps_slot_range_values_and_prompt(monkeypatch):
    monkeypatch.setattr(adaptive, "visual_enabled", lambda *_: True)
    send = AsyncMock(return_value=_message(71))
    monkeypatch.setattr(adaptive, "send_text", send)
    problem_id = uuid4()
    delta = {
        "skill": "OGE09-L1", "reason": "independent_success", "before_state": None,
        "after_state": json.dumps({"practice": 2, "stage": "practice"}),
    }
    store = SimpleNamespace(
        learner=42,
        summary_deltas=AsyncMock(return_value=[delta]),
        totals=AsyncMock(return_value={
            "solved": 3, "independent": 1, "skipped": 1, "issued": 5, "hinted": 2, "reviewed": 1,
        }),
        set_prompt=AsyncMock(),
    )
    row = {"position": 9, "id": "training", "problem": problem_id}
    await adaptive.checkpoint(_message(70), object(), store, row)
    store.summary_deltas.assert_awaited_once_with("training", from_position=5)
    store.totals.assert_awaited_once_with("training", from_position=5)
    card = send.await_args.kwargs["visual"]
    assert card.subtitle == "Задания 6–10"
    assert [m.value for m in card.metrics] == ["3/5", "1/5"]
    assert card.note == "С подсказками: 2 · Открыто разборов: 1"
    assert card.breakdown.total == 5
    assert (card.breakdown.independent, card.breakdown.assisted, card.breakdown.unsolved,
            card.breakdown.skipped) == (1, 2, 1, 1)
    assert card.sections == ()
    assert [(item.count, item.target) for item in card.practice] == [(2, 3)]
    assert "Ещё 1 самостоятельное решение для закрепления" in send.await_args.args[2]
    assert "0/3" not in send.await_args.args[2]
    markup = send.await_args.kwargs["reply_markup"]
    controls = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert controls == [
        f"ad:continue:{problem_id}", f"ad:finish:{problem_id}", f"ad:menu:{problem_id}",
    ]
    store.set_prompt.assert_awaited_once_with(42, str(problem_id), 71)

    monkeypatch.setattr(adaptive, "visual_enabled", lambda *_: False)
    await adaptive.checkpoint(_message(70), object(), store, row)
    assert send.await_args.kwargs["visual"] is None
    assert "Самостоятельно: 1 из 5" in send.await_args.args[2]
    assert "серия 0/3 → 2/3" in send.await_args.args[2]


async def test_completion_keeps_recommendation_action_and_uses_short_fallback(monkeypatch):
    family = "OGE19-LINES-ANGLES"
    selected = SelectionReason(0, family, 19, "по №19 верно 3 из 6", 10)
    monkeypatch.setattr(adaptive, "visual_enabled", lambda *_: True)
    monkeypatch.setattr(adaptive, "_learner_inputs", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(adaptive, "_select", lambda *args, **kwargs: PlanResult((), (selected,)))
    send = AsyncMock(return_value=_message(71))
    monkeypatch.setattr(adaptive, "send_text", send)
    repository = SimpleNamespace(
        personal_enabled=AsyncMock(return_value=True), save_user_state=AsyncMock(),
    )
    store = SimpleNamespace(
        learner=42,
        summary_deltas=AsyncMock(return_value=[]),
        totals=AsyncMock(return_value={"solved": 1, "independent": 1, "skipped": 1, "issued": 5}),
        excluded_for_learner=AsyncMock(return_value=[]),
        difficulties=AsyncMock(return_value={}),
    )
    await adaptive.completion(
        _message(70), repository, store, {"id": "done", "strategy": "family"},
        "Тренировка завершена.",
    )
    card = send.await_args.kwargs["visual"]
    assert card.sections[0].entries[0].label == "№19 · Прямые и углы"
    assert card.practice == ()
    fallback = send.await_args.args[2]
    assert "Что повторить" in fallback and "№19 · Прямые и углы" in fallback
    assert selected.reason not in fallback
    buttons = send.await_args.kwargs["reply_markup"].inline_keyboard
    assert buttons[0][0].callback_data == f"train:family:{family}"


def test_practice_result_omits_reset_and_prior_review_and_keeps_confirmed_type():
    def change(family, before, before_stage, after, after_stage):
        return {
            "skill": family,
            "before_state": json.dumps({"practice": before, "stage": before_stage}),
            "after_state": json.dumps({"practice": after, "stage": after_stage}),
        }

    changes = [
        change("OGE09-L1", 0, "unchecked", 1, "practice"),
        change("OGE09-L1", 1, "practice", 0, "check"),
        change("OGE19-LINES-ANGLES", 3, "confirmed", 3, "confirmed"),
        change("OGE13-L01", 2, "practice", 3, "confirmed"),
    ]
    (confirmed,) = adaptive._practice_changes(changes)
    assert confirmed.count == confirmed.target == 3
    assert confirmed.status == "Тип закреплён"


async def test_full_first_part_board_counts_one_cycle_and_keeps_next_condition(monkeypatch):
    repository = MemoryRepository()
    store = MixedTrainingRepository(repository)
    await store.start(42, list(range(1, 20)))

    def snapshot(number):
        return {"problem_id": str(uuid4()), "family_id": f"OGE{number:02}-TEST", "hints": ["hint"]}

    problem = await store.issue_current(42, 0, 1, snapshot(1))
    for number in range(1, 20):
        pid = str(problem["problem_id"])
        if number == 1:
            await store.answer(42, pid, "5", True, 100, None)
        elif number == 2:
            await store.action(42, pid, "hint")
            await store.answer(42, pid, "5", True, 101, None)
        elif number == 3:
            await store.answer(42, pid, "1", False, 102, None)
            await store.answer(42, pid, "5", True, 103, None)
        elif number == 4:
            await store.action(42, pid, "hint")
            await store.action(42, pid, "solution")
        else:
            await store.action(42, pid, "skip")
        if number < 19:
            problem = await store.advance(42, pid, snapshot(number + 1), number + 1)

    user = User(id=42, is_bot=False, first_name="Student")
    callback = CallbackQuery(
        id="next", from_user=user, chat_instance="test", message=_message(1000),
        data=f"mixed:next:{pid}",
    )
    report = AsyncMock()
    condition = AsyncMock()
    monkeypatch.setenv("OGE_VISUAL_TRAINING_RESULT_ENABLED", "true")
    monkeypatch.setenv("OGE_VISUAL_COMPANION_ONLY", "false")
    monkeypatch.setenv("OGE_VISUAL_USER_IDS", "42")
    monkeypatch.setattr(mixed_training, "send_text", report)
    monkeypatch.setattr(mixed_training, "_send_problem", condition)
    monkeypatch.setattr(mixed_training, "_scenario", lambda **_: {"cycle": 2})
    monkeypatch.setattr(mixed_training, "_scenario_question", lambda _, number: snapshot(number))
    monkeypatch.setattr(mixed_training, "answer_callback", AsyncMock())
    get_settings.cache_clear()
    try:
        await mixed_training.mixed_callback(callback, repository)
        await mixed_training.mixed_callback(callback, repository)
    finally:
        get_settings.cache_clear()

    report.assert_awaited_once()
    card = report.await_args.kwargs["visual"]
    assert [m.value for m in card.metrics] == ["3/19", "1/19"]
    assert card.note == "С подсказками: 2 · Запрошено разборов: 1"
    assert (card.breakdown.independent, card.breakdown.assisted, card.breakdown.unsolved,
            card.breakdown.skipped) == (1, 2, 1, 15)
    assert card.sections == ()
    assert "Решено верно: 3 из 19" in report.await_args.args[2]
    markup = report.await_args.kwargs["reply_markup"]
    assert [button.callback_data for row in markup.inline_keyboard for button in row] == [
        "nav:trainings", "nav:progress", "nav:main",
    ]
    condition.assert_awaited_once()
    next_state = await store.state(42)
    assert next_state["problem"]["number"] == 1
    assert next_state["problem"]["problem_id"] != pid
