from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from test_navigation_postgres import navigation_pool as postgres_db_fixture  # noqa: F401, F811

from app.bot import scenario_training
from app.math.oge07_graph import generate_graph_problem
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.persistence.error_replay import ErrorReplayRepository, load_replay_source
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import PostgresRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository
from app.persistence.training_insights import training_insights


@pytest_asyncio.fixture
async def error_replay_pool(postgres_db_fixture):  # noqa: F811
    return postgres_db_fixture


@pytest.mark.asyncio
async def test_postgres_mixed_replay_resumes_by_reference_without_changing_progress(
    error_replay_pool,
):
    user_id = 9066101
    repository = PostgresRepository(error_replay_pool)
    await repository.register_user(user_id)
    mixed = MixedTrainingRepository(repository)
    await mixed.start(user_id, [7])
    expected = await mixed.expected_number(user_id)
    assert expected is not None
    original = generate_graph_problem("OGE07-N01", 70_000_061).to_snapshot()
    issued = await mixed.issue_current(user_id, expected[1], 7, original)
    assert issued is not None
    problem_id = str(issued["problem_id"])
    wrong = await mixed.answer(user_id, problem_id, "not an answer", False, 76101, None)
    assert wrong is not None and wrong["status"] == "active"

    before = await training_insights(repository, user_id)
    assert await repository.last_training_mode(user_id) == "mixed"
    source = await load_replay_source(repository, user_id, f"m:{problem_id}")
    assert source.snapshot["condition"] == original["condition"]
    assert source.correct_answer == original["correct_answer"]
    assert source.snapshot["graph_png_base64"] == original["graph_png_base64"]

    store = ErrorReplayRepository(repository)
    first, second = await __import__("asyncio").gather(
        store.start(user_id, source), store.start(user_id, source)
    )
    assert first["id"] == second["id"]
    restarted_repo = PostgresRepository(error_replay_pool)
    restarted = ErrorReplayRepository(restarted_repo)
    assert await restarted_repo.last_training_mode(user_id) == "mixed"
    replay_id = UUID(str(first["id"]))
    await restarted.set_prompt(user_id, replay_id, 100)
    await restarted.set_prompt(user_id, replay_id, 99)
    stale = await restarted.record_attempt(user_id, replay_id, "1", False, 100, None)
    assert stale is not None and stale["event"] == "stale"
    await restarted_repo.save_user_state(user_id, "progress")
    paused = await restarted.record_attempt(user_id, replay_id, "1", False, 101, 100)
    assert paused is not None and paused["event"] == "stale"
    resumed = await restarted.status_for_source(user_id, "mixed", UUID(problem_id), 0)
    assert resumed is not None and resumed["id"] == first["id"]
    assert await error_replay_pool.fetchval(
        "SELECT count(*) FROM training_error_replays WHERE source_id=$1::uuid", problem_id
    ) == 1
    after = await training_insights(PostgresRepository(error_replay_pool), user_id)
    assert after == before


@pytest.mark.asyncio
async def test_postgres_mixed_scenario_question_replays_from_original_shared_snapshot(
    error_replay_pool,
):
    from app.bot.mixed_training import _issue, _scenario, _scenario_question

    user_id = 9066103
    repository = PostgresRepository(error_replay_pool)
    await repository.register_user(user_id)
    store = MixedTrainingRepository(repository)
    await store.start(user_id, [1])
    expected = await store.expected_number(user_id)
    assert expected is not None
    scenario = _scenario(seed=661_003)
    current = await store.issue_current(
        user_id,
        expected[1],
        1,
        _scenario_question(scenario, 1),
        scenario_snapshot=scenario,
    )
    assert current is not None

    for position in (1, 2):
        assert current["number"] == position
        answered = await store.answer(
            user_id,
            str(current["problem_id"]),
            str(current["correct_answer"]),
            True,
            66_100 + position,
            None,
        )
        assert answered is not None and answered["status"] == "solved"
        transition = await store.advance(user_id, str(current["problem_id"]), None, None)
        assert transition is not None and transition["number"] == position + 1
        store = MixedTrainingRepository(PostgresRepository(error_replay_pool))
        current = await _issue(store, user_id)
        assert current is not None

    assert current["number"] == 3
    attempted = await store.answer(
        user_id, str(current["problem_id"]), "wrong", False, 66_103, None
    )
    assert attempted is not None and attempted["status"] == "active"

    original = current
    for position in (3, 4, 5):
        assert current["number"] == position
        solved = await store.answer(
            user_id, str(current["problem_id"]), str(current["correct_answer"]),
            True, 67_100 + position, None,
        )
        assert solved is not None and solved["status"] == "solved"
        transition = await store.advance(
            user_id, str(current["problem_id"]), None, None, new_cycle=[6],
        )
        assert transition is not None
        if position < 5:
            current = await _issue(store, user_id)
            assert current is not None
    assert transition["number"] == 6
    current_session = await store.state(user_id)
    assert current_session is not None
    assert current_session["state"]["scenario_snapshot"] is None
    assert "scenario_archive" not in current_session["state"]

    source = await load_replay_source(
        PostgresRepository(error_replay_pool),
        user_id,
        f"m:{original['problem_id']}",
    )
    assert source.number == 3
    assert source.scenario_snapshot == scenario
    assert source.condition == original["condition"]
    assert source.correct_answer == original["correct_answer"]


@pytest.mark.asyncio
async def test_postgres_practical_question_replay_restores_same_scenario_position(
    error_replay_pool,
):
    user_id = 9066102
    other_user = user_id + 1
    repository = PostgresRepository(error_replay_pool)
    await repository.register_user(user_id)
    await repository.register_user(other_user)
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, 661_005, story_code="TARIFF", position=3),
        scenario_training.public_registry(),
    )
    scenarios = ScenarioPostgresRepository(error_replay_pool)
    session = await scenarios.start_session(
        user_id, plan.snapshot, PracticeMode.SINGLE, (3,)
    )
    assert session is not None
    assert await scenarios.set_condition_message(user_id, session.session_id, 3, 76300)
    attempt = await scenarios.record_attempt(
        telegram_user_id=user_id,
        session_id=session.session_id,
        position=3,
        telegram_message_id=76301,
        raw_answer="-1",
        normalized_answer="-1",
        is_correct=False,
        reply_to_message_id=76300,
    )
    assert attempt.value == "accepted"

    source_ref = f"s:{session.session_id}:3"
    source = await load_replay_source(repository, user_id, source_ref)
    assert source.number == 3
    assert source.snapshot["story_code"] == "TARIFF"
    assert source.scenario_snapshot is not None
    assert source.snapshot["condition"] == plan.snapshot.questions[2].condition
    with pytest.raises(ValueError):
        await load_replay_source(repository, other_user, source_ref)

    before = await training_insights(repository, user_id)
    store = ErrorReplayRepository(repository)
    replay = await store.start(user_id, source)
    persisted = await error_replay_pool.fetchrow(
        "SELECT * FROM training_error_replays WHERE id=$1::uuid", replay["id"]
    )
    assert persisted is not None
    assert "snapshot" not in persisted
    assert persisted["source_type"] == "scenario"
    assert persisted["source_position"] == 3
    assert await load_replay_source(
        PostgresRepository(error_replay_pool), user_id, source_ref
    ) == source
    assert await training_insights(PostgresRepository(error_replay_pool), user_id) == before


@pytest.mark.asyncio
async def test_similar_practical_error_starts_new_question_in_same_story_and_position(
    error_replay_pool,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.bot.progress import encode_record_ref, progress_navigation

    user_id = 9066135
    repository = PostgresRepository(error_replay_pool)
    await repository.register_user(user_id)
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 66_030, story_code="FLAT"),
        scenario_training.public_registry(),
    )
    scenarios = ScenarioPostgresRepository(error_replay_pool)
    original = await scenarios.start_session(user_id, plan.snapshot, PracticeMode.SINGLE, (3,))
    assert original is not None
    assert await scenarios.set_condition_message(user_id, original.session_id, 3, 77110)
    assert (await scenarios.record_attempt(
        telegram_user_id=user_id, session_id=original.session_id, position=3,
        telegram_message_id=77111, raw_answer="-1", normalized_answer="-1",
        is_correct=False, reply_to_message_id=77110,
    )).value == "accepted"

    token = encode_record_ref(f"s:{original.session_id}:3")
    msg = AsyncMock()
    msg.from_user = SimpleNamespace(id=user_id, is_bot=False)
    msg.message_id = 77112
    msg.answer.return_value.message_id = 77113
    before = await training_insights(repository, user_id)
    await progress_navigation(msg, repository, user_id, f"similar:{token}")
    saved = await scenarios.resume_session(user_id, original.session_id)
    assert saved is not None and saved.attempt_count == 1
    assert await training_insights(repository, user_id) == before

    await progress_navigation(msg, repository, user_id, f"similar:{token}:y")
    current = await ScenarioPostgresRepository(error_replay_pool).last_used_session(user_id)
    assert current is not None and current.session_id != original.session_id
    assert current.current_position == 3
    assert current.snapshot.story_code == original.snapshot.story_code
    assert current.snapshot.questions[2].family_id == original.snapshot.questions[2].family_id
    assert current.attempt_count == 0
    assert current.snapshot.seed != original.snapshot.seed
    assert await load_replay_source(repository, user_id, f"s:{original.session_id}:3")
    after = await training_insights(repository, user_id)
    assert after["total"]["issued"] == before["total"]["issued"] + 1
    assert after["total"]["attempts"] == before["total"]["attempts"]
