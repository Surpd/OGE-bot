from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User
from PIL import Image

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
async def test_mixed_oge19_multiple_true_answers_use_text_and_ignore_order(monkeypatch):
    from app.math.oge19_scheduler import build_task19_candidate_batch

    candidate = build_task19_candidate_batch({}, 101, enabled_families=("OGE19-MIXED",))[0]
    expected = str(candidate["correct_answer"])
    assert len(expected) == 2
    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [19])
    monkeypatch.setattr(mixed_training, "_candidate", lambda number, state=None: candidate)

    prompt_id = 5100
    delivered = {}

    async def capture_text(*_args, **kwargs):
        delivered.update(kwargs)
        return SimpleNamespace(message_id=prompt_id)

    monkeypatch.setattr(mixed_training, "send_text", capture_text)
    incoming = AsyncMock()
    incoming.from_user = User(id=819, is_bot=False, first_name="Student")
    repository = MemoryRepository()
    await mixed_training.start_mixed(incoming, repository)

    store = MixedTrainingRepository(repository)
    current = await store.state(819)
    assert current is not None
    problem = current["problem"]
    assert problem["condition"].startswith(
        "Какие из следующих утверждений верны? В ответ запишите их номера."
    )
    labels = [
        button.text
        for row in delivered["reply_markup"].inline_keyboard
        for button in row
    ]
    assert not {"1", "2", "3"}.intersection(labels)

    answer = AsyncMock()
    answer.from_user = incoming.from_user
    answer.message_id = 5101
    answer.reply_to_message = SimpleNamespace(message_id=problem["prompt_message_id"])
    answer.text = expected[::-1]
    await mixed_training.mixed_answer(answer, repository)
    solved = await store.state(819)
    assert solved is not None and solved["problem"]["outcome"] == "solved"


def test_mixed_task19_does_not_leak_number_of_true_statements_through_buttons():
    from app.bot.mixed_training import _task19_button_choices
    from app.math.oge19 import LEGACY_ANSWER_POLICY_ID
    from app.math.oge19_scheduler import build_task19_candidate_batch

    single = build_task19_candidate_batch({}, 100)[0]
    multiple = build_task19_candidate_batch({}, 101)[0]
    assert len(str(single["correct_answer"])) == 1
    assert len(str(multiple["correct_answer"])) == 2
    assert _task19_button_choices(single) == 0
    assert _task19_button_choices(multiple) == 0

    # Already-issued pre-v4 tasks retain their working answer buttons.
    legacy = {**single, "answer_policy_id": LEGACY_ANSWER_POLICY_ID}
    assert _task19_button_choices(legacy) == 3


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
    monkeypatch.setattr(mixed_training, "send_photo", outbound)
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

    # A completed problem must still offer Next after leaving and resuming.
    await store.pause(794)
    await repository.save_user_state(794, "main_menu")
    assert await mixed_training.continue_mixed(incoming, repository, 794)
    reopened = await store.state(794)
    assert reopened is not None
    assert reopened["problem"]["problem_id"] == first_id
    assert reopened["problem"]["outcome"] == "solved"
    markup = outbound.await_args.kwargs["reply_markup"]
    actions = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    }
    assert f"mixed:next:{first_id}" in actions
    assert not any(
        action.startswith(("mixed:hint:", "mixed:skip:", "mixed:pick:"))
        for action in actions if action is not None
    )

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


@pytest.mark.parametrize("number", [7, 11, 13, 15, 16, 17, 18, 19])
@pytest.mark.asyncio
async def test_telegram_mixed_graphical_and_choice_families(number: int, monkeypatch):
    repository = MemoryRepository()
    candidate = _candidate(number)
    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [number])
    monkeypatch.setattr(mixed_training, "_candidate", lambda requested, state=None: candidate)

    sent: list[tuple[str, bytes | None, str]] = []
    next_message_id = 2_000

    async def capture_text(*args, **kwargs):
        nonlocal next_message_id
        next_message_id += 1
        sent.append(("text", None, str(args[2]) if len(args) > 2 else ""))
        return SimpleNamespace(message_id=next_message_id)

    async def capture_photo(message, repository, photo, *, caption=None, **kwargs):
        nonlocal next_message_id
        next_message_id += 1
        sent.append(("photo", bytes(photo.data), str(caption or "")))
        return SimpleNamespace(message_id=next_message_id)

    monkeypatch.setattr(mixed_training, "send_text", capture_text)
    monkeypatch.setattr(mixed_training, "send_photo", capture_photo)
    monkeypatch.setattr(mixed_training, "answer_callback", AsyncMock())

    incoming = AsyncMock()
    incoming.from_user = User(id=81_000 + number, is_bot=False, first_name="Student")
    await mixed_training.start_mixed(incoming, repository)
    store = MixedTrainingRepository(repository)
    state = await store.state(incoming.from_user.id)
    assert state is not None
    problem = state["problem"]
    assert problem["number"] == number
    expected_png = mixed_training._render_image(number, candidate)
    photo_messages = [data for kind, data, _ in sent if kind == "photo" and data]
    assert bool(photo_messages) is (expected_png is not None)
    if expected_png is not None:
        with Image.open(BytesIO(photo_messages[-1])) as image:
            assert image.format == "PNG"
            image.verify()

    problem_id = str(problem["problem_id"])
    if number == 13 or (number == 19 and len(str(problem["correct_answer"])) == 1):
        chat_message = Message(
            message_id=2_500,
            date=datetime.now(UTC),
            chat=Chat(id=incoming.from_user.id, type="private"),
            text="Выбрать",
        )
        callback = CallbackQuery(
            id=f"mixed-choice-{number}",
            from_user=incoming.from_user,
            chat_instance="mixed-e2e",
            message=chat_message.model_copy(
                update={"message_id": int(problem["prompt_message_id"])}
            ),
            data=f"mixed:pick:{problem_id}:{problem['correct_answer']}",
        )
        await mixed_training.mixed_callback(callback, repository)
    else:
        answer = AsyncMock()
        answer.from_user = incoming.from_user
        answer.message_id = 2_501
        answer.reply_to_message = SimpleNamespace(
            message_id=problem["prompt_message_id"]
        )
        answer.text = (
            str(problem["correct_answer"])[::-1]
            if number == 19
            else str(problem["correct_answer"])
        )
        await mixed_training.mixed_answer(answer, repository)

    solved = await store.state(incoming.from_user.id)
    assert solved is not None and solved["problem"]["outcome"] == "solved"
    assert solved["problem"]["attempts"] == 1


@pytest.mark.asyncio
async def test_telegram_mixed_story_five_questions_then_ordinary_and_resume(monkeypatch):
    repository = MemoryRepository()
    scenario = _scenario(seed=815_019)
    ordinary = _candidate(6)
    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [1, 6])
    monkeypatch.setattr(mixed_training, "_scenario", lambda: scenario)
    monkeypatch.setattr(mixed_training, "_candidate", lambda number, state=None: ordinary)
    monkeypatch.setattr(mixed_training, "_render_image", lambda number, problem: None)
    outbound = AsyncMock()
    outbound.side_effect = lambda *args, **kwargs: SimpleNamespace(
        message_id=3_000 + outbound.await_count
    )
    monkeypatch.setattr(mixed_training, "send_text", outbound)
    monkeypatch.setattr(mixed_training, "send_photo", outbound)
    monkeypatch.setattr(mixed_training, "answer_callback", AsyncMock())
    monkeypatch.setattr(
        mixed_training.secrets,
        "SystemRandom",
        lambda: SimpleNamespace(shuffle=lambda sequence: None),
    )

    incoming = AsyncMock()
    incoming.from_user = User(id=81_100, is_bot=False, first_name="Student")
    await mixed_training.start_mixed(incoming, repository)
    store = MixedTrainingRepository(repository)
    for position in range(1, 6):
        current = await store.state(81_100)
        assert current is not None
        problem = current["problem"]
        assert problem["number"] == position
        assert problem["scenario_snapshot"] == scenario
        assert problem["scenario_seed"] == scenario["seed"]
        assert problem["shared_context"] == scenario["shared_context"]
        answer = AsyncMock()
        answer.from_user = incoming.from_user
        answer.message_id = 4_000 + position
        answer.reply_to_message = SimpleNamespace(
            message_id=problem["prompt_message_id"]
        )
        answer.text = str(problem["correct_answer"])
        await mixed_training.mixed_answer(answer, repository)
        next_callback = CallbackQuery(
            id=f"mixed-story-next-{position}",
            from_user=incoming.from_user,
            chat_instance="mixed-story-e2e",
            message=Message(
                message_id=4_500 + position,
                date=datetime.now(UTC),
                chat=Chat(id=81_100, type="private"),
                text="Далее",
            ),
            data=f"mixed:next:{problem['problem_id']}",
        )
        await mixed_training.mixed_callback(next_callback, repository)

    completed_story = await store.state(81_100)
    assert completed_story is not None
    assert completed_story["problem"]["number"] == 6
    old_callback = CallbackQuery(
        id="mixed-story-old-callback",
        from_user=incoming.from_user,
        chat_instance="mixed-story-e2e",
        message=Message(
            message_id=4_600,
            date=datetime.now(UTC),
            chat=Chat(id=81_100, type="private"),
            text="Старое задание",
        ),
        data="mixed:next:mixed-scenario-old-id",
    )
    await mixed_training.mixed_callback(old_callback, repository)
    assert (await store.state(81_100))["problem"]["number"] == 6

    current_id = str(completed_story["problem"]["problem_id"])
    menu_callback = CallbackQuery(
        id="mixed-menu-callback",
        from_user=incoming.from_user,
        chat_instance="mixed-story-e2e",
        message=Message(
            message_id=4_700,
            date=datetime.now(UTC),
            chat=Chat(id=81_100, type="private"),
            text="Меню",
        ),
        data=f"mixed:menu:{current_id}",
    )
    await mixed_training.mixed_callback(menu_callback, repository)
    assert await mixed_training.continue_mixed(incoming, repository, 81_100)
    resumed = await store.state(81_100)
    assert resumed is not None
    assert resumed["problem"]["problem_id"] == current_id
    assert resumed["problem"]["number"] == 6


@pytest.mark.asyncio
async def test_candidate_generation_failure_keeps_session_and_can_be_retried(monkeypatch):
    repository = MemoryRepository()
    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [6])

    def unavailable(number: int, state=None):
        raise RuntimeError("temporary generator failure")

    monkeypatch.setattr(mixed_training, "_candidate", unavailable)
    outbound = AsyncMock(return_value=SimpleNamespace(message_id=8_001))
    monkeypatch.setattr(mixed_training, "send_text", outbound)
    incoming = AsyncMock()
    incoming.from_user = User(id=81_200, is_bot=False, first_name="Student")

    await mixed_training.start_mixed(incoming, repository)
    assert "Продолжить" in outbound.await_args.args[2]
    state = await MixedTrainingRepository(repository).state(81_200)
    assert state is not None and state.get("problem") is None
    assert await repository.user_state(81_200) == "mixed"

    monkeypatch.setattr(mixed_training, "_candidate", lambda number, state=None: _candidate(6))
    assert await mixed_training.continue_mixed(incoming, repository, 81_200)
    resumed = await MixedTrainingRepository(repository).state(81_200)
    assert resumed is not None and resumed["problem"]["outcome"] == "issued"


@pytest.mark.asyncio
async def test_next_candidate_failure_preserves_completed_problem_for_safe_retry(monkeypatch):
    repository = MemoryRepository()
    first = _candidate(6)
    second = {**first, "problem_id": str(uuid4()), "fingerprint": str(uuid4())}
    calls = 0

    def candidate(number: int, state=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        if calls == 2:
            raise RuntimeError("temporary generator failure")
        return second

    monkeypatch.setattr(mixed_training, "available_numbers", lambda: [6])
    monkeypatch.setattr(mixed_training, "_candidate", candidate)
    monkeypatch.setattr(mixed_training, "_render_image", lambda number, problem: None)
    outbound = AsyncMock()
    outbound.side_effect = lambda *args, **kwargs: SimpleNamespace(
        message_id=9_000 + outbound.await_count
    )
    monkeypatch.setattr(mixed_training, "send_text", outbound)
    monkeypatch.setattr(mixed_training, "answer_callback", AsyncMock())
    incoming = AsyncMock()
    incoming.from_user = User(id=81_201, is_bot=False, first_name="Student")
    await mixed_training.start_mixed(incoming, repository)
    store = MixedTrainingRepository(repository)
    current = await store.state(81_201)
    assert current is not None
    problem = current["problem"]

    answer = AsyncMock()
    answer.from_user = incoming.from_user
    answer.message_id = 9_100
    answer.reply_to_message = SimpleNamespace(message_id=problem["prompt_message_id"])
    answer.text = str(problem["correct_answer"])
    await mixed_training.mixed_answer(answer, repository)

    callback = CallbackQuery(
        id="mixed-next-retry",
        from_user=incoming.from_user,
        chat_instance="mixed-retry",
        message=Message(
            message_id=9_200,
            date=datetime.now(UTC),
            chat=Chat(id=81_201, type="private"),
            text="Следующее",
        ),
        data=f"mixed:next:{problem['problem_id']}",
    )
    await mixed_training.mixed_callback(callback, repository)
    failed_transition = await store.state(81_201)
    assert failed_transition is not None
    assert failed_transition["problem"]["problem_id"] == problem["problem_id"]
    assert failed_transition["problem"]["outcome"] == "solved"
    assert "Следующее" in outbound.await_args.args[2]

    await mixed_training.mixed_callback(callback, repository)
    retried = await store.state(81_201)
    assert retried is not None
    assert retried["problem"]["problem_id"] == second["problem_id"]
    assert retried["problem"]["outcome"] == "issued"
