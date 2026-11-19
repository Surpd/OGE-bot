from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.math.oge17_generator import generate as generate_task17
from app.persistence.error_replay import (
    ErrorReplayRepository,
    _assert_regenerated,
    _digest,
    load_replay_source,
)
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import training_insights


@pytest.mark.asyncio
async def test_memory_replay_is_reference_only_one_time_and_excluded_from_progress():
    repository = MemoryRepository()
    user_id = 9066001
    problem = generate_task17("OGE17-R03", 17_000_321).to_snapshot()
    problem_id = str(problem["problem_id"])
    repository.issued17[user_id] = {problem_id: problem}
    repository.outcomes17[user_id] = {problem_id: "failed"}
    repository.attempts17[user_id] = [
        {"problem_id": problem_id, "attempt_no": 1, "is_correct": False},
        {"problem_id": problem_id, "attempt_no": 2, "is_correct": False},
    ]
    source_ref = f"o:{problem_id}"
    before = await training_insights(repository, user_id)
    source = await load_replay_source(repository, user_id, source_ref)
    assert source.snapshot == problem
    assert source.number == 17
    assert source.correct_answer == problem["correct_answer"]

    store = ErrorReplayRepository(repository)
    first = await store.start(user_id, source)
    duplicate = await store.start(user_id, source)
    assert first["id"] == duplicate["id"]
    assert len(repository._training_error_replays) == 1
    assert "snapshot" not in first and "png_base64" not in first

    replay_id = UUID(str(first["id"]))
    await store.set_prompt(user_id, replay_id, 32100)
    assert await store.action(user_id, replay_id, "hint", source.snapshot)
    assert repository._training_error_replays[(user_id, "ordinary", problem_id, 0)][
        "hints_used"
    ] == 1
    stale = await store.record_attempt(user_id, replay_id, "не ответ", False, 32100, 999)
    assert stale is not None and stale["event"] == "stale"
    wrong = await store.record_attempt(user_id, replay_id, "не ответ", False, 32101, 32100)
    assert wrong is not None and wrong["status"] == "active"
    duplicate_attempt = await store.record_attempt(
        user_id, replay_id, "не ответ", False, 32101, 32100
    )
    assert duplicate_attempt is not None and duplicate_attempt["event"] == "duplicate"
    correct = await store.record_attempt(
        user_id, replay_id, source.correct_answer, True, 32102, 32100
    )
    assert correct is not None and correct["status"] == "solved"
    after = await training_insights(repository, user_id)
    assert after == before


@pytest.mark.asyncio
async def test_memory_replay_closes_self_score_after_solution_and_checks_owner():
    repository = MemoryRepository()
    problem = generate_task17("OGE17-R03", 17_000_322).to_snapshot()
    problem_id = str(problem["problem_id"])
    repository.issued17[10] = {problem_id: problem}
    repository.outcomes17[10] = {problem_id: "failed"}
    repository.attempts17[10] = [{"problem_id": problem_id, "attempt_no": 1, "is_correct": False}]
    source = await load_replay_source(repository, 10, f"o:{problem_id}")
    store = ErrorReplayRepository(repository)
    replay = await store.start(10, source)
    replay_id = UUID(str(replay["id"]))
    assert await store.action(11, replay_id, "solution", source.snapshot) is None
    revealed = await store.action(10, replay_id, "solution", source.snapshot)
    assert revealed
    assert repository._training_error_replays[(10, "ordinary", problem_id, 0)]["status"] == (
        "solution_viewed"
    )
    closed_attempt = await store.record_attempt(10, replay_id, "999", True, 32110, None)
    assert closed_attempt is not None and closed_attempt["event"] == "closed"


@pytest.mark.asyncio
async def test_memory_mixed_position_three_recovers_original_shared_scenario_after_exit():
    from app.bot.mixed_training import _scenario, _scenario_question

    repository = MemoryRepository()
    from app.persistence.mixed_training import MixedTrainingRepository

    MixedTrainingRepository(repository)
    user_id = 13
    scenario = _scenario(seed=661_003)
    first_id = "00000000-0000-4000-8000-000000006613"
    third_id = "00000000-0000-4000-8000-000000006615"
    first = _scenario_question(scenario, 1)
    third = _scenario_question(scenario, 3)
    first_snapshot = {
        **first,
        "problem_id": first_id,
        "_original_scenario_snapshot": scenario,
        "_original_scenario_snapshot_sha256": _digest(scenario),
    }
    third_snapshot = {**third, "problem_id": third_id}
    repository._mixed_training_records[user_id] = [
        {
            "id": first_id,
            "record_id": f"m:{first_id}",
            "problem_id": first_id,
            "number": 1,
            "family_id": first["family_id"],
            "condition": first["condition"],
            "outcome": "solved",
            "attempt_records": [{"attempt_no": 1, "is_correct": True}],
            "snapshot": first_snapshot,
        },
        {
            "id": third_id,
            "record_id": f"m:{third_id}",
            "problem_id": third_id,
            "number": 3,
            "family_id": third["family_id"],
            "condition": third["condition"],
            "outcome": "issued",
            "attempt_records": [{"attempt_no": 1, "is_correct": False}],
            "snapshot": third_snapshot,
        },
    ]
    repository._mixed_training_sessions[user_id] = {"state": {"scenario_snapshot": None}}

    source = await load_replay_source(repository, user_id, f"m:{third_id}")
    assert source.number == 3
    assert source.scenario_snapshot == scenario
    assert source.condition == third["condition"]
    assert source.correct_answer == third["correct_answer"]


@pytest.mark.asyncio
async def test_memory_replay_fails_closed_for_a_different_seed_snapshot_substitution():
    repository = MemoryRepository()
    user_id = 12
    original = generate_task17("OGE17-R03", 17_000_323).to_snapshot()
    substituted = generate_task17("OGE17-R03", 17_000_324).to_snapshot()
    problem_id = str(original["problem_id"])
    substituted["problem_id"] = problem_id
    repository.issued17[user_id] = {problem_id: substituted}
    repository.outcomes17[user_id] = {problem_id: "failed"}
    repository.attempts17[user_id] = [
        {"problem_id": problem_id, "attempt_no": 1, "is_correct": False}
    ]
    with pytest.raises(ValueError):
        await load_replay_source(repository, user_id, f"o:{problem_id}")


@pytest.mark.asyncio
async def test_telegram_replay_answer_flow_keeps_two_attempts_out_of_progress(
    monkeypatch,
):
    from app.bot import error_replay

    repository = MemoryRepository()
    user_id = 15
    problem = generate_task17("OGE17-R03", 17_000_325).to_snapshot()
    problem_id = str(problem["problem_id"])
    repository.issued17[user_id] = {problem_id: problem}
    repository.outcomes17[user_id] = {problem_id: "failed"}
    repository.attempts17[user_id] = [
        {"problem_id": problem_id, "attempt_no": 1, "is_correct": False}
    ]
    before = await training_insights(repository, user_id)
    source = await load_replay_source(repository, user_id, f"o:{problem_id}")
    store = ErrorReplayRepository(repository)
    replay = await store.start(user_id, source)
    replay_id = UUID(str(replay["id"]))
    await store.set_prompt(user_id, replay_id, 400)
    monkeypatch.setattr(error_replay, "_feedback", AsyncMock())

    def answer_message(message_id: int, text: str):
        return SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            text=text,
            message_id=message_id,
            reply_to_message=None,
        )

    wrong_value = str(int(float(source.correct_answer)) + 10)
    await error_replay.answer(answer_message(401, wrong_value), repository)
    active = repository._training_error_replays[(user_id, "ordinary", problem_id, 0)]
    assert active["status"] == "active" and active["attempt_count"] == 1
    await error_replay.answer(answer_message(402, source.correct_answer), repository)
    solved = repository._training_error_replays[(user_id, "ordinary", problem_id, 0)]
    assert solved["status"] == "solved" and solved["attempt_count"] == 2
    assert (await training_insights(repository, user_id)) == before
    assert error_replay._feedback.await_count == 2


def test_replay_callback_ids_remain_compact_and_record_refs_round_trip():
    from app.bot.error_replay import _keyboard, replay_token
    from app.bot.navigation import prepare_navigation_markup
    from app.bot.progress import decode_record_ref, encode_record_ref, progress_keyboard

    scenario_ref = "s:7fd6324e-65e0-4563-b294-1a073e654321:5"
    encoded = encode_record_ref(scenario_ref)
    assert decode_record_ref(encoded) == scenario_ref
    item_markup = progress_keyboard(
        "item",
        return_page="errors:0",
        replay_action=("🔄 Повторить исходное", f"progress:replay:{encoded}"),
    )
    item_markup = prepare_navigation_markup(item_markup)
    callbacks = [button.callback_data for row in item_markup.inline_keyboard for button in row]
    assert all(value is None or len(value.encode("utf-8")) <= 64 for value in callbacks)

    replay_markup = prepare_navigation_markup(_keyboard(replay_token(UUID(scenario_ref[2:38]))))
    replay_callbacks = [
        button.callback_data
        for row in replay_markup.inline_keyboard
        for button in row
    ]
    assert all(value is None or len(value.encode("utf-8")) <= 64 for value in replay_callbacks)


def test_deterministic_recovery_dispatch_checks_seed_and_version_for_numbers_6_to_14():
    from app.bot.error_replay import _accepts
    from app.math import (
        equations,
        formulas,
        generator,
        inequalities,
        numbers,
        oge8,
        oge11,
        probability,
        progressions,
    )
    from app.persistence.error_replay import ReplaySource

    cases = (
        (generator.generate(generator.GENERATOR_SPECS[0].family_id, 610_001), 6),
        (numbers.generate(numbers.FAMILIES[0], 710_001), 7),
        (oge8.generate(oge8.ENABLED_FAMILIES[0], 810_001), 8),
        (equations.generate_equation(equations.ENABLED_FAMILIES[0], 910_001), 9),
        (probability.generate(probability.ENABLED_FAMILIES[0], 1_010_001), 10),
        (oge11.generate(oge11.FAMILIES[0], 1_110_001), 11),
        (formulas.generate(formulas.ENABLED_FAMILIES[0], 1_210_001), 12),
        (inequalities.generate(inequalities.FAMILIES[0], 1_310_001), 13),
        (progressions.generate(progressions.ALL_FAMILIES[0], 1_410_001), 14),
    )
    for problem, number in cases:
        snapshot = problem.to_snapshot()
        problem_id = UUID(str(snapshot["problem_id"]))
        _assert_regenerated(snapshot, str(problem_id))
        source = ReplaySource("ordinary", problem_id, 0, number, snapshot)
        assert _accepts(source, source.correct_answer) is True, number


def test_replay_restores_text_options_and_all_scenario_materials():
    from app.bot.error_replay import _accepts, _condition, _materials
    from app.bot.scenario_training import public_registry
    from app.math.inequalities import generate
    from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
    from app.math.scenarios.mobile_photos import scenario_photos_for_question
    from app.persistence.error_replay import ReplaySource, _scenario_question

    problem = generate("OGE13-L01", 13_066).to_snapshot()
    source = ReplaySource("ordinary", UUID(str(problem["problem_id"])), 0, 13, problem)
    assert _materials(source) == ("", ())
    assert _accepts(source, source.correct_answer) is True
    wrong = next(str(n) for n in range(1, 5) if str(n) != source.correct_answer)
    assert _accepts(source, wrong) is False
    assert _accepts(source, "5") is None
    assert all(
        f"{index}. {choice}" in _condition(source)
        for index, choice in enumerate(problem["option_texts"], 1)
    )
    scenario = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 66_002, story_code="PAPER"), public_registry()
    ).snapshot
    photo_case = next(
        position for position in range(1, 6)
        if len(scenario_photos_for_question(scenario, position)) > 1
    )
    source = ReplaySource(
        "scenario", source.source_id, photo_case, photo_case,
        _scenario_question(scenario.to_snapshot(), photo_case), scenario.to_snapshot(),
    )
    context, photos = _materials(source)
    assert scenario.shared_context.splitlines()[0] in context
    assert photos == scenario_photos_for_question(scenario, photo_case)


def test_replay_uses_legacy_statement_policy_and_choice_bounds():
    import json
    from pathlib import Path

    from app.bot.error_replay import _accepts
    from app.math.oge07_graph import generate_graph_problem
    from app.persistence.error_replay import ReplaySource

    legacy = json.loads(Path("tests/fixtures/oge19/snapshot_v1_seed_20261117.json").read_text())
    source = ReplaySource("ordinary", UUID(int=1), 0, 19, {
        **legacy, "correct_answer": legacy["answer_mask"],
    })
    assert _accepts(source, source.correct_answer) is True
    assert _accepts(source, "13") is None
    graph = generate_graph_problem("OGE07-N01", 66_019).to_snapshot()
    source = ReplaySource("ordinary", UUID(str(graph["problem_id"])), 0, 7, graph)
    assert _accepts(source, "0") is None
    assert _accepts(source, source.correct_answer) is True
