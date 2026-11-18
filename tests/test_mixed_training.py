from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot import mixed_training
from app.bot.mixed_training import (
    _candidate,
    _is_correct,
    _scenario,
    _scenario_question,
    available_numbers,
)
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import training_insights


@pytest.mark.asyncio
async def test_all_public_numbers_and_linked_scenario_answers_are_reachable():
    numbers = available_numbers()
    assert numbers == [1, *range(6, 20)]

    for number in range(6, 20):
        problem = _candidate(number)
        assert _is_correct(number, problem, str(problem["correct_answer"])) is True

    scenario = _scenario(seed=192507)
    for number in range(1, 6):
        problem = _scenario_question(scenario, number)
        assert _is_correct(number, problem, str(problem["correct_answer"])) is True
        assert problem["scenario_snapshot"] == scenario


@pytest.mark.asyncio
async def test_memory_session_replays_same_snapshot_and_counts_one_result():
    repository = MemoryRepository()
    store = MixedTrainingRepository(repository)
    user_id = 791
    session = await store.start(user_id, [6])
    expected = await store.expected_number(user_id)
    assert expected is not None
    snapshot = {
        "problem_id": "b2e37f02-108a-43b9-9407-92bfb94e338f",
        "family_id": "OGE06-test",
        "fingerprint": "stable-content",
        "condition": "Вычислите.",
        "correct_answer": "5",
        "hints": ["Сложите числа."],
        "solution": ["2 + 3 = 5."],
    }
    issued = await store.issue_current(user_id, expected[1], 6, snapshot)
    assert issued is not None
    await store.set_prompt(user_id, str(issued["problem_id"]), 100)

    restarted = MixedTrainingRepository(repository)
    resumed = await restarted.start(user_id, [6])
    assert resumed["id"] == session["id"]
    restored = await restarted.state(user_id)
    assert restored is not None
    assert restored["problem"]["problem_id"] == issued["problem_id"]
    assert restored["problem"]["condition"] == snapshot["condition"]
    generator_states = restored["state"]["generator_states"]
    assert generator_states["6"]["recent_fingerprints"] == ["stable-content"]

    assert await restarted.action(user_id, str(issued["problem_id"]), "hint")
    first = await restarted.answer(user_id, str(issued["problem_id"]), "4", False, 101, 100)
    duplicate = await restarted.answer(
        user_id, str(issued["problem_id"]), "4", False, 101, 100
    )
    second = await restarted.answer(user_id, str(issued["problem_id"]), "4", False, 102, 100)
    assert first is not None and first["status"] == "active"
    assert duplicate == {"status": "duplicate"}
    assert second is not None and second["status"] == "failed"

    metrics = await training_insights(repository, user_id)
    assert metrics["total"]["issued"] == 1
    assert metrics["total"]["attempts"] == 2
    assert metrics["total"]["failed"] == 1
    assert metrics["total"]["hints_used"] == 1


@pytest.mark.asyncio
async def test_mixed_candidate_selection_reuses_scheduler_recent_fingerprints():
    repository = MemoryRepository()
    store = MixedTrainingRepository(repository)
    user_id = 795
    await store.start(user_id, [6])
    expected = await store.expected_number(user_id)
    assert expected is not None
    first = _candidate(6)
    issued = await store.issue_current(user_id, expected[1], 6, first)
    assert issued is not None
    state = await store.state(user_id)
    assert state is not None and isinstance(state["state"], dict)
    generator_states = state["state"].get("generator_states")
    assert isinstance(generator_states, dict)
    next_state = generator_states.get("6")
    assert isinstance(next_state, dict)
    second = _candidate(6, next_state)
    assert second["fingerprint"] != first["fingerprint"]


@pytest.mark.asyncio
async def test_mixed_session_does_not_replace_an_ordinary_saved_task():
    repository = MemoryRepository()
    await repository.ensure_task6_session(792)
    original = await repository.advance_task6_problem(
        792,
        None,
        [
            {
                "problem_id": "ordinary-task-snapshot",
                "family_id": "OGE06-F001",
                "condition": "Обычное задание.",
                "correct_answer": "7",
                "answer_policy_id": "oge6.oge06-f001-add.numeric",
                "answer_policy_version": "1",
                "fingerprint": "ordinary-fingerprint",
            }
        ],
    )
    await repository.save_user_state(792, "task6")

    await MixedTrainingRepository(repository).start(792, [6])
    restored = await repository.task6_state(792)
    assert restored is not None
    assert restored["problem"]["problem_id"] == original["problem_id"]
    assert restored["problem"]["fingerprint"] == "ordinary-fingerprint"


@pytest.mark.asyncio
async def test_mixed_story_block_uses_one_saved_scenario_for_all_five_questions():
    repository = MemoryRepository()
    store = MixedTrainingRepository(repository)
    user_id = 793
    await store.start(user_id, [1])
    scenario = _scenario(seed=192508)
    first = await store.expected_number(user_id)
    assert first is not None
    problem = await store.issue_current(
        user_id,
        first[1],
        1,
        _scenario_question(scenario, 1),
        scenario_snapshot=scenario,
    )
    assert problem is not None
    story_code = problem["story_code"]

    for position in range(1, 6):
        assert problem["scenario_seed"] == scenario["seed"]
        assert problem["story_code"] == story_code
        assert problem["number"] == position
        assert await store.answer(
            user_id,
            str(problem["problem_id"]),
            str(problem["correct_answer"]),
            True,
            1000 + position,
            None,
        )
        if position < 5:
            result = await store.advance(user_id, str(problem["problem_id"]), None, None)
            assert result is not None
            problem = result

    assert [record["number"] for record in repository._mixed_training_records[user_id][-5:]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert all(
        "scenario_snapshot" not in record
        for record in repository._mixed_training_records[user_id][-5:]
    )


@pytest.mark.asyncio
async def test_telegram_mixed_route_accepts_answer_and_advances(monkeypatch):
    repository = MemoryRepository()
    candidate = _candidate(6)
    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [6])
    monkeypatch.setattr(mixed_training, "_render_image", lambda number, problem: None)

    def next_candidate(number: int, state: object = None) -> dict[str, object]:
        return {
            **candidate,
            "problem_id": str(uuid4()),
            "fingerprint": str(uuid4()),
            "correct_answer": "5",
            "number": number,
        }

    monkeypatch.setattr(mixed_training, "_candidate", next_candidate)
    outbound = AsyncMock()
    outbound.side_effect = lambda *args, **kwargs: SimpleNamespace(
        message_id=501 + outbound.await_count
    )
    monkeypatch.setattr(mixed_training, "send_text", outbound)
    monkeypatch.setattr(mixed_training, "answer_callback", AsyncMock())

    incoming = AsyncMock()
    incoming.from_user = User(id=794, is_bot=False, first_name="Student")
    await mixed_training.start_mixed(incoming, repository)
    store = MixedTrainingRepository(repository)
    current = await store.state(794)
    assert current is not None and current["problem"]["number"] == 6
    first_id = str(current["problem"]["problem_id"])
    prompt_id = int(current["problem"]["prompt_message_id"])

    answer = AsyncMock()
    answer.from_user = incoming.from_user
    answer.message_id = prompt_id + 1
    answer.reply_to_message = SimpleNamespace(message_id=prompt_id)
    answer.text = "5"
    await mixed_training.mixed_answer(answer, repository)
    solved = await store.state(794)
    assert solved is not None and solved["problem"]["outcome"] == "solved"

    control_message = Message(
        message_id=700,
        date=datetime.now(UTC),
        chat=Chat(id=794, type="private"),
        text="Готово",
    )
    callback = CallbackQuery(
        id="mixed-next-callback",
        from_user=incoming.from_user,
        chat_instance="mixed-test",
        message=control_message,
        data=f"mixed:next:{first_id}",
    )
    await mixed_training.mixed_callback(callback, repository)
    next_state = await store.state(794)
    assert next_state is not None
    assert next_state["problem"]["problem_id"] != first_id
    assert next_state["problem"]["outcome"] == "issued"
    assert next_state["state"]["generator_states"]["6"]["recent_fingerprints"][-1] == (
        next_state["problem"]["fingerprint"]
    )
    assert [row["outcome"] for row in repository._mixed_training_records[794]] == [
        "solved",
        "issued",
    ]
    next_id = str(next_state["problem"]["problem_id"])
    next_condition = str(next_state["problem"]["condition"])
    await mixed_training.mixed_callback(callback, repository)
    assert str((await store.state(794))["problem"]["problem_id"]) == next_id

    await store.pause(794)
    await repository.save_user_state(794, "main_menu")
    assert await mixed_training.continue_mixed(
        incoming, repository, 794
    )
    resumed = await store.state(794)
    assert resumed is not None
    assert resumed["problem"]["problem_id"] == next_id
    assert resumed["problem"]["condition"] == next_condition
