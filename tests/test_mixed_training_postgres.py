from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest
from aiogram.types import CallbackQuery, Chat, Message, User
from PIL import Image

from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import PostgresRepository, read_migration
from app.persistence.rotation_history import candidate_state
from app.persistence.training_insights import training_insights


@pytest.mark.asyncio
async def test_postgres_mixed_session_resume_attempt_dedupe_and_progress(monkeypatch) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    connection = await asyncpg.connect(database_url)
    schema = f"test_mixed_{uuid4().hex}"
    pool: asyncpg.Pool | None = None
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        assert int(await connection.fetchval("SHOW server_version_num")) >= 170000
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=4,
            server_settings={"search_path": f'"{schema}", public'},
        )
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))

        repo = PostgresRepository(pool)
        store = MixedTrainingRepository(repo)
        ordered = [1, *range(6, 20)]
        ordered_session = await store.start(user_id + 500, ordered)
        assert ordered_session["state"]["queue"] == ordered
        assert await store.expected_number(user_id + 500) == (1, 0)
        started = await store.start(user_id, [6])
        expected = await store.expected_number(user_id)
        assert expected is not None
        number, revision = expected
        snapshot = {
            "problem_id": str(uuid4()),
            "family_id": f"OGE{number:02}-MIXED-TEST",
            "fingerprint": "postgres-mixed-fixture",
            "condition": "Вычислите.",
            "correct_answer": "5",
            "hints": ["Сложите числа."],
            "solution": ["2 + 3 = 5."],
        }
        issued = await store.issue_current(user_id, revision, number, snapshot)
        assert issued is not None
        problem_id = str(issued["problem_id"])
        assert await store.set_prompt(user_id, problem_id, 901)

        restarted = MixedTrainingRepository(PostgresRepository(pool))
        await restarted.start(user_id, [6])
        restored = await restarted.state(user_id)
        assert restored is not None
        assert restored["id"] == started["id"]
        assert restored["problem"]["problem_id"] == problem_id
        assert restored["problem"]["condition"] == "Вычислите."
        assert await restarted.action(user_id, problem_id, "hint")

        wrong = await restarted.answer(user_id, problem_id, "4", False, 902, 901)
        duplicate = await restarted.answer(user_id, problem_id, "4", False, 902, 901)
        assert wrong is not None and wrong["status"] == "active"
        assert duplicate == {"status": "duplicate"}
        switched_bot = MixedTrainingRepository(PostgresRepository(pool, bot_id=100002))
        second = await switched_bot.answer(user_id, problem_id, "4", False, 902, 901)
        assert second is not None and second["status"] == "failed"
        assert await restarted.cycle_results(user_id, problem_id) == [{
            "number": 6, "outcome": "failed", "attempt_no": None, "used_hint": None,
            "hints_used": 1,
        }]
        assert not await restarted.cycle_results(user_id + 500, problem_id)

        summary = await training_insights(PostgresRepository(pool), user_id)
        assert summary["total"]["issued"] == 1
        assert summary["total"]["attempts"] == 2
        assert summary["total"]["failed"] == 1
        assert summary["total"]["hints_used"] == 1

        from app.bot import mixed_training
        from app.bot.mixed_training import _scenario, _scenario_question

        story_user_id = user_id + 1
        story_store = MixedTrainingRepository(PostgresRepository(pool))
        await story_store.start(story_user_id, [1])
        story_expected = await story_store.expected_number(story_user_id)
        assert story_expected is not None
        scenario = _scenario(seed=192509)
        story_problem = await story_store.issue_current(
            story_user_id,
            story_expected[1],
            1,
            _scenario_question(scenario, 1),
            scenario_snapshot=scenario,
        )
        assert story_problem is not None
        stored_question = await pool.fetchval(
            "SELECT snapshot FROM mixed_training_problems WHERE id=$1::uuid",
            story_problem["problem_id"],
        )
        stored_question = json.loads(stored_question)
        assert "scenario_snapshot" not in stored_question
        assert stored_question["_original_scenario_snapshot"] == json.loads(json.dumps(scenario))
        restored_story = await story_store.state(story_user_id)
        assert restored_story is not None
        assert restored_story["problem"]["scenario_snapshot"] == scenario
        story_history = await training_insights(
            PostgresRepository(pool), story_user_id, "history:0"
        )
        assert len(story_history["history"]) == 1
        assert story_history["history"][0]["story_code"] == scenario["story_code"]
        from app.bot.progress import render_progress
        from app.persistence.training_insights import _STORY_NAMES

        rendered_story = render_progress(story_history, "history:0")
        assert f"№1–5 · {_STORY_NAMES[scenario['story_code']]}, вопрос 1" in rendered_story
        assert "Тип из прежней версии" not in rendered_story
        from app.persistence.training_insights import training_record_detail

        story_detail = await training_record_detail(
            PostgresRepository(pool), story_user_id, f"m:{story_problem['problem_id']}"
        )
        assert story_detail is not None
        assert story_detail["story_code"] == scenario["story_code"]
        assert story_detail["condition"] == story_problem["condition"]

        # Simulate a process death after the position transaction commits but
        # before issue_current() claims and stores the next scenario question.
        from app.bot.mixed_training import _issue
        from app.math.scenario_engine import ScenarioSnapshot

        canonical_scenario = ScenarioSnapshot.from_snapshot(scenario)
        shared_context = canonical_scenario.shared_context
        current = story_problem
        for position in range(1, 5):
            assert current["number"] == position
            assert current["scenario_seed"] == scenario["seed"]
            assert current["story_code"] == scenario["story_code"]
            assert current["shared_context"] == shared_context
            expected_question = canonical_scenario.questions[position - 1]
            assert current["condition"] == expected_question.condition
            assert current["correct_answer"] == expected_question.canonical_answer
            answered = await story_store.answer(
                story_user_id,
                str(current["problem_id"]),
                str(current["correct_answer"]),
                True,
                10_000 + position,
                None,
            )
            assert answered is not None and answered["status"] == "solved"
            transition = await story_store.advance(
                story_user_id, str(current["problem_id"]), None, None
            )
            assert transition is not None
            assert transition["number"] == position + 1
            assert transition["pending_snapshot"] is None

            # A new repository instance models a restarted application process.
            story_store = MixedTrainingRepository(PostgresRepository(pool))
            await story_store.start(story_user_id, [1])
            current = await _issue(story_store, story_user_id)
            assert current is not None
            assert current["number"] == position + 1
            assert current["scenario_seed"] == scenario["seed"]
            assert current["story_code"] == scenario["story_code"]
            assert current["shared_context"] == shared_context
            assert current["scenario_snapshot"] == scenario
            expected_question = canonical_scenario.questions[position]
            assert current["condition"] == expected_question.condition
            assert current["correct_answer"] == expected_question.canonical_answer

        skip_user_id = story_user_id + 1
        skip_store = MixedTrainingRepository(PostgresRepository(pool))
        await skip_store.start(skip_user_id, [1])
        skip_expected = await skip_store.expected_number(skip_user_id)
        assert skip_expected is not None
        skip_scenario = _scenario(seed=192510)
        skip_problem = await skip_store.issue_current(
            skip_user_id, skip_expected[1], 1, _scenario_question(skip_scenario, 1),
            scenario_snapshot=skip_scenario,
        )
        assert skip_problem is not None
        unissued = await training_insights(PostgresRepository(pool), skip_user_id)
        assert unissued["total"]["issued"] == 1
        assert unissued["total"]["skipped"] == 0
        assert all(
            unissued["numbers"][position]["issued"] == 0
            and unissued["numbers"][position]["skipped"] == 0
            for position in range(2, 6)
        )
        assert await skip_store.action(skip_user_id, str(skip_problem["problem_id"]), "skip")
        skipped = await training_insights(PostgresRepository(pool), skip_user_id)
        assert skipped["total"]["issued"] == 1
        assert skipped["total"]["skipped"] == 1

        assert current["number"] == 5
        final_answer = await story_store.answer(
            story_user_id,
            str(current["problem_id"]),
            str(current["correct_answer"]),
            True,
            10_005,
            None,
        )
        assert final_answer is not None and final_answer["status"] == "solved"
        ordinary_candidate = mixed_training._candidate(6)
        ordinary_transition = await story_store.advance(
            story_user_id,
            str(current["problem_id"]),
            ordinary_candidate,
            6,
            new_cycle=[6],
        )
        assert ordinary_transition is not None
        pending_ordinary = ordinary_transition["pending_snapshot"]
        assert isinstance(pending_ordinary, dict)
        ordinary_problem = await story_store.issue_current(
            story_user_id,
            int(ordinary_transition["expected_revision"]),
            6,
            pending_ordinary,
        )
        assert ordinary_problem is not None and ordinary_problem["number"] == 6
        ordinary_state = await story_store.state(story_user_id)
        assert ordinary_state is not None
        assert ordinary_state["state"]["scenario_snapshot"] is None

        # A fresh ordinary handler sees only this learner's mixed issues.
        reopened = PostgresRepository(pool)
        history = await candidate_state(reopened, story_user_id, 6, {})
        assert ordinary_candidate["fingerprint"] in history["recent_fingerprints"]
        assert await candidate_state(reopened, user_id + 10000, 6, {}) == {}
        from app.math.scenario_engine import ScenarioSnapshot
        from app.math.scenarios.recent_questions import question_signature

        restored_story = ScenarioSnapshot.from_snapshot(scenario)
        assert await story_store.recent_story_questions(story_user_id) == frozenset(
            question_signature(restored_story, q) for q in restored_story.questions
        )
        assert not await story_store.mixed_story_questions(user_id + 10000)
        assert await story_store.story_families(story_user_id) == [
            question["family_id"] for question in reversed(scenario["questions"])
        ]

        # Two competing advances cannot issue two next problems.
        candidates = [
            {
                "problem_id": str(uuid4()),
                "family_id": "OGE06-MIXED-TEST",
                "fingerprint": f"next-{index}",
                "condition": "Новое задание.",
                "correct_answer": "1",
            }
            for index in range(2)
        ]
        advanced = await asyncio.gather(
            restarted.advance(user_id, problem_id, candidates[0], number, new_cycle=[number]),
            restarted.advance(user_id, problem_id, candidates[1], number, new_cycle=[number]),
        )
        assert sum(result is not None for result in advanced) == 1
        transition = next(result for result in advanced if result is not None)
        pending = transition.get("pending_snapshot")
        assert isinstance(pending, dict)
        opened = await restarted.issue_current(
            user_id,
            int(transition["expected_revision"]),
            int(transition["number"]),
            pending,
        )
        assert opened is not None
        current = await restarted.state(user_id)
        assert current is not None and current["problem"]["condition"] == "Новое задание."

        # Exercise the real mixed Telegram entry and answer handlers against
        # PostgreSQL for every graphical/choice number in the requested range.
        from io import BytesIO

        from app.bot import mixed_training
        from app.math.oge13_scheduler import build_task13_candidate_batch

        sent: list[tuple[str, bytes | None]] = []
        rendered_system_rows: list[tuple[str, ...] | None] = []
        message_id = 20_000

        async def capture_text(*args, **kwargs):
            nonlocal message_id
            message_id += 1
            sent.append(("text", None))
            rendered_system_rows.append(kwargs.get("math_system_rows"))
            return SimpleNamespace(message_id=message_id)

        async def capture_photo(message, repository, photo, **kwargs):
            nonlocal message_id
            message_id += 1
            raw = bytes(photo.data)
            sent.append(("photo", raw))
            rendered_system_rows.append(kwargs.get("math_system_rows"))
            return SimpleNamespace(message_id=message_id)

        async def ack_callback(*args, **kwargs):
            return None

        monkeypatch.setattr(mixed_training, "send_text", capture_text)
        monkeypatch.setattr(mixed_training, "send_photo", capture_photo)
        monkeypatch.setattr(mixed_training, "answer_callback", ack_callback)
        # Find one text-only and one graphical №13 family using a fixed bounded
        # seed scan; this verifies both presentation branches without random retries.
        task13_text = {"OGE13-L01", "OGE13-Q01", "OGE13-Q02", "OGE13-Q03"}
        task13_fixtures: dict[str, dict[str, object]] = {}
        for fixture_seed in range(64):
            batch = build_task13_candidate_batch({}, fixture_seed, limit=1)
            if not batch:
                continue
            fixture = batch[0]
            category = "text" if fixture["family_id"] in task13_text else "graphic"
            task13_fixtures.setdefault(category, fixture)
            if len(task13_fixtures) == 2:
                break
        assert set(task13_fixtures) == {"text", "graphic"}

        task13_system_fixtures = {}
        for system_family in ("OGE13-S01", "OGE13-S02", "OGE13-S03"):
            system_batch = build_task13_candidate_batch(
                {"family_queue": [system_family]}, 1400 + len(task13_system_fixtures), limit=1
            )
            assert system_batch and system_batch[0]["family_id"] == system_family
            task13_system_fixtures[system_family] = system_batch[0]

        cases: list[tuple[int, dict[str, object]]] = []
        for number in (7, 11, 15, 16, 17, 18, 19):
            cases.append((number, mixed_training._candidate(number)))
        cases.extend((13, fixture) for fixture in task13_fixtures.values())
        cases.extend((13, fixture) for fixture in task13_system_fixtures.values())
        real_candidate = mixed_training._candidate
        for index, (number, candidate_fixture) in enumerate(cases, 1):
            sent.clear()
            rendered_system_rows.clear()
            student_id = user_id + 10_000 + index
            numbers = [7, 6] if number == 7 else [number]
            monkeypatch.setattr(mixed_training, "available_numbers", lambda values=numbers: values)

            def fixture_candidate(
                requested: int,
                state=None,
                *,
                selected_number: int = number,
                fixture: dict[str, object] = candidate_fixture,
            ) -> dict[str, object]:
                if requested == selected_number:
                    return fixture
                return real_candidate(requested, state)

            monkeypatch.setattr(mixed_training, "_candidate", fixture_candidate)
            incoming = SimpleNamespace(
                from_user=User(id=student_id, is_bot=False, first_name="Student")
            )
            repository_for_user = PostgresRepository(pool)
            await mixed_training.start_mixed(incoming, repository_for_user)
            student_store = MixedTrainingRepository(PostgresRepository(pool))
            student_state = await student_store.state(student_id)
            assert student_state is not None
            problem = student_state["problem"]
            assert problem["number"] == number
            assert problem["family_id"] == candidate_fixture["family_id"]
            if number == 13 and str(problem["family_id"]).startswith("OGE13-S"):
                assert rendered_system_rows[-1] == tuple(
                    str(problem["condition"]).splitlines()
                )
            prompt_id = int(problem["prompt_message_id"])
            delivered_photos = [raw for kind, raw in sent if kind == "photo" and raw]
            expected_png = await asyncio.to_thread(
                mixed_training._render_image, number, candidate_fixture
            )
            assert bool(expected_png) is bool(delivered_photos)
            if expected_png is not None:
                with Image.open(BytesIO(delivered_photos[-1])) as image:
                    assert image.format == "PNG"
                    image.verify()

            if number == 7 or (
                number == 13 and str(problem["family_id"]).startswith("OGE13-S")
            ) or number == 19:
                exit_callback = CallbackQuery(
                    id="mixed-pg-menu-exit",
                    from_user=incoming.from_user,
                    chat_instance="mixed-pg",
                    message=Message(
                        message_id=prompt_id,
                        date=datetime.now(UTC),
                        chat=Chat(id=student_id, type="private"),
                        text="Задание",
                    ),
                    data=f"mixed:menu:{problem['problem_id']}",
                )
                await mixed_training.mixed_callback(
                    exit_callback, repository_for_user
                )
                assert await mixed_training.continue_mixed(
                    incoming, repository_for_user, student_id
                )
                resumed = await MixedTrainingRepository(
                    PostgresRepository(pool)
                ).state(student_id)
                assert resumed is not None
                assert resumed["problem"]["problem_id"] == problem["problem_id"]
                problem = resumed["problem"]
                prompt_id = int(problem["prompt_message_id"])

            if number == 13:
                callback_message = Message(
                    message_id=prompt_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=student_id, type="private"),
                    text="Выбор",
                )
                callback = CallbackQuery(
                    id=f"mixed-pg-choice-{index}",
                    from_user=incoming.from_user,
                    chat_instance="mixed-pg",
                    message=callback_message,
                    data=f"mixed:pick:{problem['problem_id']}:{problem['correct_answer']}",
                )
                await mixed_training.mixed_callback(callback, repository_for_user)
            else:
                answer_text = str(problem["correct_answer"])
                if number == 19:
                    answer_text = answer_text[::-1]
                answer_message = SimpleNamespace(
                    from_user=incoming.from_user,
                    text=answer_text,
                    message_id=30_000 + index,
                    reply_to_message=SimpleNamespace(message_id=prompt_id),
                )
                await mixed_training.mixed_answer(answer_message, repository_for_user)
            verified = await MixedTrainingRepository(PostgresRepository(pool)).state(student_id)
            assert verified is not None
            assert verified["problem"]["outcome"] == "solved"
            assert verified["problem"]["correct_answer"] == problem["correct_answer"]
            if number == 7:
                next_callback = CallbackQuery(
                    id="mixed-pg-next-after-oge7",
                    from_user=incoming.from_user,
                    chat_instance="mixed-pg",
                    message=Message(
                        message_id=prompt_id,
                        date=datetime.now(UTC),
                        chat=Chat(id=student_id, type="private"),
                        text="Следующее",
                    ),
                    data=f"mixed:next:{problem['problem_id']}",
                )
                await mixed_training.mixed_callback(next_callback, repository_for_user)
                advanced_state = await MixedTrainingRepository(
                    PostgresRepository(pool)
                ).state(student_id)
                assert advanced_state is not None
                assert advanced_state["problem"]["number"] == 6
                active_id = str(advanced_state["problem"]["problem_id"])
                stale_callback = CallbackQuery(
                    id="mixed-pg-stale-oge7-button",
                    from_user=incoming.from_user,
                    chat_instance="mixed-pg",
                    message=next_callback.message,
                    data=f"mixed:hint:{problem['problem_id']}",
                )
                await mixed_training.mixed_callback(stale_callback, repository_for_user)
                after_stale = await MixedTrainingRepository(
                    PostgresRepository(pool)
                ).state(student_id)
                assert after_stale is not None
                assert after_stale["problem"]["problem_id"] == active_id
    finally:
        if pool is not None:
            await pool.close()
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
