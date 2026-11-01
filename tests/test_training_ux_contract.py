"""Shared, parameterized black-box UX contract for every enabled training number."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.menu import number_menu
from app.bot.router import (
    choose_task6,
    choose_task9,
    choose_task10,
    choose_task12,
    choose_task14,
    task6_answer,
    task6_callback,
    task9_answer,
    task9_callback,
    task10_answer,
    task10_callback,
    task12_answer,
    task12_callback,
    task14_answer,
    task14_callback,
    unknown_message,
)
from app.math import oge14_scheduler
from app.math.oge9_scheduler import build_task9_candidate_batch
from app.math.oge10_scheduler import build_task10_candidate_batch
from app.math.oge12_scheduler import build_task12_candidate_batch
from app.math.oge14_scheduler import build_task14_candidate_batch
from app.math.progressions import A01
from app.math.scheduler import build_candidate_batch
from app.persistence.repository import MemoryRepository


@dataclass(frozen=True)
class TrainingAdapter:
    number: int
    choose: Any
    answer: Any
    callback: Any
    advance: Any
    set_condition: Any
    candidates: Any
    state: Any
    progress: Any


TRAININGS = (
    TrainingAdapter(
        6,
        choose_task6,
        task6_answer,
        task6_callback,
        "advance_task6_problem",
        "set_task6_condition_message",
        build_candidate_batch,
        "task6_state",
        "task6_progress",
    ),
    TrainingAdapter(
        9,
        choose_task9,
        task9_answer,
        task9_callback,
        "advance_task9_problem",
        "set_task9_condition_message",
        build_task9_candidate_batch,
        "task9_state",
        "task9_progress",
    ),
    TrainingAdapter(
        10,
        choose_task10,
        task10_answer,
        task10_callback,
        "advance_task10_problem",
        "set_task10_condition_message",
        build_task10_candidate_batch,
        "task10_state",
        "task10_progress",
    ),
    TrainingAdapter(
        12,
        choose_task12,
        task12_answer,
        task12_callback,
        "advance_task12_problem",
        "set_task12_condition_message",
        build_task12_candidate_batch,
        "task12_state",
        "task12_progress",
    ),
    TrainingAdapter(
        14,
        choose_task14,
        task14_answer,
        task14_callback,
        "advance_task14_problem",
        "set_task14_condition_message",
        build_task14_candidate_batch,
        "task14_state",
        "task14_progress",
    ),
)
TRAINING_CASES = pytest.mark.parametrize(
    "training", TRAININGS, ids=lambda item: f"task{item.number}"
)


def test_number_menu_matches_registered_training_adapters() -> None:
    menu_numbers = {
        int(match.group(1))
        for row in number_menu().keyboard
        for button in row
        if (match := re.match(r"№(\d+)", button.text or "")) is not None
    }
    registered_numbers = {training.number for training in TRAININGS}

    assert menu_numbers == registered_numbers


_message_id = 910_000


def _message(user_id: int, text: str, *, message_id: int | None = None) -> AsyncMock:
    global _message_id
    incoming = message_id if message_id is not None else _message_id
    _message_id = max(_message_id, incoming + 2)
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = incoming
    message.reply_to_message = None
    message.answer.return_value.message_id = incoming + 1
    return message


def _callback(
    user_id: int, number: int, action: str, problem_id: str, control_id: int
) -> AsyncMock:
    callback = AsyncMock()
    callback.data = f"t{number}:{action}:{problem_id}"
    callback.from_user = User(id=user_id, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = control_id
    callback.message.answer.return_value.message_id = control_id + 1
    return callback


async def _open(repository: MemoryRepository, training: TrainingAdapter, user_id: int):
    await training.choose(_message(user_id, f"№{training.number}"), repository)
    state = await getattr(repository, training.state)(user_id)
    assert state is not None and isinstance(state.get("problem"), dict)
    return state


@pytest.mark.asyncio
@TRAINING_CASES
async def test_contract_accepts_plain_answer_and_enforces_two_attempts(
    training: TrainingAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 920_000 + training.number
    state = await _open(repository, training, user_id)
    problem = state["problem"]
    first_prompt_id = int(state["state"]["problem_prompt_message_id"])

    malformed = _message(user_id, "ответ")
    await training.answer(malformed, repository)
    after_malformed = await getattr(repository, training.state)(user_id)
    assert after_malformed is not None and after_malformed["state"]["attempts"] == 0

    correct = str(problem["correct_answer"])
    wrong_text = "-999999" if correct == "999999" else "999999"
    first = _message(user_id, wrong_text)
    assert first.message_id > first_prompt_id
    await training.answer(first, repository)
    active = await getattr(repository, training.state)(user_id)
    assert active is not None and active["state"]["attempts"] == 1
    assert correct not in first.answer.await_args.args[0]

    second = _message(user_id, correct)
    second.reply_to_message = SimpleNamespace(message_id=first_prompt_id)
    await training.answer(second, repository)
    solved = await getattr(repository, training.state)(user_id)
    assert solved is not None and solved["state"]["status"] == "solved"
    progress = await getattr(repository, training.progress)(user_id)
    assert progress["attempts"] == 2 and progress["correct"] == 1


@pytest.mark.asyncio
@TRAINING_CASES
async def test_contract_next_never_skips_but_skip_records_one_outcome(
    training: TrainingAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 930_000 + training.number
    state = await _open(repository, training, user_id)
    problem_id = str(state["problem"]["problem_id"])
    control_id = int(state["state"]["input_prompt_message_id"])

    await training.callback(
        _callback(user_id, training.number, "next", problem_id, control_id), repository
    )
    unchanged = await getattr(repository, training.state)(user_id)
    assert unchanged is not None and unchanged["problem"]["problem_id"] == problem_id
    assert (await getattr(repository, training.progress)(user_id))["skipped"] == 0

    await training.callback(
        _callback(user_id, training.number, "skip", problem_id, control_id), repository
    )
    advanced = await getattr(repository, training.state)(user_id)
    assert advanced is not None and advanced["problem"]["problem_id"] != problem_id
    progress = await getattr(repository, training.progress)(user_id)
    assert progress["issued"] == 2 and progress["skipped"] == 1

    await training.callback(
        _callback(user_id, training.number, "skip", problem_id, control_id), repository
    )
    repeated = await getattr(repository, training.state)(user_id)
    assert (
        repeated is not None
        and repeated["problem"]["problem_id"] == advanced["problem"]["problem_id"]
    )
    assert (await getattr(repository, training.progress)(user_id))["issued"] == 2


@pytest.mark.asyncio
@TRAINING_CASES
async def test_contract_solution_view_closes_scoring_and_keeps_next(
    training: TrainingAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 940_000 + training.number
    state = await _open(repository, training, user_id)
    problem_id = str(state["problem"]["problem_id"])
    control_id = int(state["state"]["input_prompt_message_id"])
    await training.callback(
        _callback(user_id, training.number, "solution", problem_id, control_id), repository
    )
    viewed = await getattr(repository, training.state)(user_id)
    assert viewed is not None and viewed["state"]["status"] == "solution_viewed"
    await training.answer(_message(user_id, str(viewed["problem"]["correct_answer"])), repository)
    progress = await getattr(repository, training.progress)(user_id)
    assert progress["correct"] == 0 and progress["solutions_viewed"] == 1

    current_control = int(viewed["state"]["input_prompt_message_id"])
    await training.callback(
        _callback(user_id, training.number, "next", problem_id, current_control), repository
    )
    next_state = await getattr(repository, training.state)(user_id)
    assert next_state is not None and next_state["problem"]["problem_id"] != problem_id


@pytest.mark.asyncio
@TRAINING_CASES
async def test_contract_duplicate_message_and_text_after_completion_are_idempotent(
    training: TrainingAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 950_000 + training.number
    state = await _open(repository, training, user_id)
    problem_id = str(state["problem"]["problem_id"])
    answer = _message(user_id, str(state["problem"]["correct_answer"]))
    await training.answer(answer, repository)
    await training.answer(answer, repository)
    progress_before = await getattr(repository, training.progress)(user_id)
    assert progress_before["correct"] == 1 and progress_before["attempts"] == 1

    stray = _message(user_id, "спасибо, готово")
    await unknown_message(stray, repository)
    saved = await getattr(repository, training.state)(user_id)
    assert saved is not None and saved["problem"]["problem_id"] == problem_id
    assert await repository.user_state(user_id) == f"task{training.number}"
    assert "Следующее" in stray.answer.await_args.args[0]


@pytest.mark.asyncio
@TRAINING_CASES
async def test_contract_old_reply_is_rejected_without_consuming_current_attempt(
    training: TrainingAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 960_000 + training.number
    original = await _open(repository, training, user_id)
    old_id = str(original["problem"]["problem_id"])
    old_condition_id = int(original["state"]["problem_prompt_message_id"])
    schedule_state = dict(original["state"])
    schedule_state["recent_fingerprints"] = [
        *cast(list[str], schedule_state.get("recent_fingerprints", [])),
        str(original["problem"]["fingerprint"]),
    ]
    next_candidates = training.candidates(schedule_state, 960_000 + training.number)
    advance = getattr(repository, training.advance)
    await advance(user_id, old_id, next_candidates, skip_active=True)
    new_state = await getattr(repository, training.state)(user_id)
    assert new_state is not None
    current = new_state["problem"]
    assert await getattr(repository, training.set_condition)(
        user_id, str(current["problem_id"]), old_condition_id + 10
    )
    old_reply = _message(user_id, "1")
    old_reply.reply_to_message = SimpleNamespace(message_id=old_condition_id)
    await training.answer(old_reply, repository)
    after = await getattr(repository, training.state)(user_id)
    assert after is not None and after["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_contract_sessions_for_numbers_do_not_share_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oge14_scheduler, "ENABLED_FAMILIES", (A01,))
    repository = MemoryRepository()
    user_id = 970_006
    states = {}
    for training in TRAININGS:
        states[training.number] = await _open(repository, training, user_id)
    active = TRAININGS[-1]
    await active.answer(_message(user_id, "999999"), repository)
    for training in TRAININGS:
        state = await getattr(repository, training.state)(user_id)
        assert state is not None
        expected_attempts = 1 if training.number == active.number else 0
        assert state["state"]["attempts"] == expected_attempts
        assert state["problem"]["problem_id"] == states[training.number]["problem"]["problem_id"]
