"""Mixed first-part flow, backed by its own durable session and snapshots."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from collections.abc import Callable
from typing import Any, cast

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.callbacks import answer_callback
from app.bot.menu import main_menu
from app.bot.presentation import hint_message, send_photo, send_text
from app.bot.scenario_training import public_registry
from app.bot.training_ux import matches_current_condition
from app.bot.trainings import TRAININGS
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    build_practice_plan,
)
from app.math.scenarios.mobile_photos import scenario_photos_for_question
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import Repository


class _CandidateUnavailable(RuntimeError):
    """A single bounded generation attempt could not produce the next task."""


def _mixed_menu(
    problem_id: str, *, completed: bool = False, choices: int = 0
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if choices:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(value), callback_data=f"mixed:pick:{problem_id}:{value}"
                )
                for value in range(1, choices + 1)
            ]
        )
    if completed:
        rows.append(
            [InlineKeyboardButton(text="➡ Следующее", callback_data=f"mixed:next:{problem_id}")]
        )
    else:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="💡 Подсказка", callback_data=f"mixed:hint:{problem_id}"
                    ),
                    InlineKeyboardButton(
                        text="📘 Разбор", callback_data=f"mixed:solution:{problem_id}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⏭ Пропустить", callback_data=f"mixed:skip:{problem_id}"
                    )
                ],
            ]
        )
    rows.append([InlineKeyboardButton(text="↩ В меню", callback_data=f"mixed:menu:{problem_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _builders() -> dict[int, Callable[[dict[str, object], int], list[dict[str, object]]]]:
    from app.math.oge07_scheduler import build_task7_candidate_batch
    from app.math.oge8_scheduler import build_task8_candidate_batch
    from app.math.oge9_scheduler import build_task9_candidate_batch
    from app.math.oge10_scheduler import build_task10_candidate_batch
    from app.math.oge11_scheduler import build_task11_candidate_batch
    from app.math.oge12_scheduler import build_task12_candidate_batch
    from app.math.oge13_scheduler import build_task13_candidate_batch
    from app.math.oge14_scheduler import build_task14_candidate_batch
    from app.math.oge15_scheduler import build_task15_candidate_batch
    from app.math.oge16_scheduler import build_task16_candidate_batch
    from app.math.oge17_scheduler import build_task17_candidate_batch
    from app.math.oge18_scheduler import build_task18_candidate_batch
    from app.math.oge19_scheduler import build_task19_candidate_batch
    from app.math.scheduler import build_candidate_batch

    return {
        6: build_candidate_batch,
        7: build_task7_candidate_batch,
        8: build_task8_candidate_batch,
        9: build_task9_candidate_batch,
        10: build_task10_candidate_batch,
        11: build_task11_candidate_batch,
        12: build_task12_candidate_batch,
        13: build_task13_candidate_batch,
        14: build_task14_candidate_batch,
        15: build_task15_candidate_batch,
        16: build_task16_candidate_batch,
        17: build_task17_candidate_batch,
        18: build_task18_candidate_batch,
        19: build_task19_candidate_batch,
    }


def available_numbers() -> list[int]:
    result = [training.number for training in TRAININGS if training.available]
    try:
        if public_registry().available_stories(PracticeMode.FULL):
            result.insert(0, 1)  # One queue slot denotes a linked five-question scenario.
    except (ValueError, RuntimeError):
        pass
    return result


def _candidate(number: int, state: dict[str, object] | None = None) -> dict[str, object]:
    candidates = _builders()[number](state or {}, secrets.randbelow(2**63))
    if not candidates:
        raise RuntimeError(f"No public candidates for OGE {number}")
    return candidates[0]


def _scenario(seed: int | None = None) -> dict[str, object]:
    actual_seed = seed if seed is not None else secrets.randbelow(2**63)
    plan = build_practice_plan(PracticeRequest(PracticeMode.FULL, actual_seed), public_registry())
    return plan.snapshot.to_snapshot()


def _scenario_question(snapshot: dict[str, object], position: int) -> dict[str, object]:
    from app.persistence.mixed_training import _scenario_question as question_snapshot

    return question_snapshot(snapshot, position)


def _callback_dedupe_id(callback: CallbackQuery) -> int:
    digest = hashlib.sha256(callback.id.encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1) or 1


def _number_list(value: object) -> list[int]:
    return [item for item in value if isinstance(item, int)] if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _render_image(number: int, problem: dict[str, object]) -> bytes | None:
    raw = problem.get("graph_png_base64") if number == 7 else problem.get("png_base64")
    if isinstance(raw, str):
        try:
            return base64.b64decode(raw, validate=True)
        except ValueError as exc:
            raise ValueError("Mixed task image is invalid") from exc
    if number == 7:
        return None
    if number == 11:
        from app.math.oge11 import from_snapshot as restore_oge11

        return restore_oge11(problem).png_bytes
    if number == 13 and str(problem.get("family_id", "")) not in {
        "OGE13-L01",
        "OGE13-Q01",
        "OGE13-Q02",
        "OGE13-Q03",
    }:
        from app.math.inequalities import render_option_sheet_snapshot_png

        return render_option_sheet_snapshot_png(problem)
    if number == 15:
        from app.math.oge15_triangles import from_snapshot as restore_oge15

        png_bytes = restore_oge15(problem).png_bytes
        return png_bytes if png_bytes else None
    if number == 16:
        from app.math.oge16_circles import from_snapshot as restore_oge16

        return restore_oge16(problem).png
    if number == 17:
        from app.math.oge17_generator import from_snapshot as restore_oge17

        restored = restore_oge17(
            problem, expected_problem_id=str(problem["problem_id"])
        ).to_snapshot()
        png = restored.get("png_base64")
        if not isinstance(png, str):
            raise ValueError("Mixed task 17 snapshot has no PNG")
        return base64.b64decode(
            png
        )
    if number == 18:
        from app.math.oge18 import from_snapshot as restore_oge18

        return restore_oge18(problem).png_bytes
    return None


def _is_correct(number: int, problem: dict[str, object], raw: str) -> bool | None:
    policy_id = str(problem.get("answer_policy_id", ""))
    version = str(problem.get("answer_policy_version", ""))
    family = str(problem.get("family_id", ""))
    if 1 <= number <= 5:
        scenario = problem.get("scenario_snapshot")
        if not isinstance(scenario, dict):
            return None
        restored = ScenarioSnapshot.from_snapshot(scenario)
        question = restored.questions[number - 1]
        adapter = public_registry().adapter(restored.story_code)
        scenario_policy = adapter.answer_policies.get(
            (question.answer_policy_id, question.answer_policy_version)
        )
        if scenario_policy is None or problem.get("family_id") != question.family_id:
            return None
        from app.bot.scenario_training import _valid_answer_format

        if not _valid_answer_format(restored.story_code, question.answer_policy_id, raw):
            return None
        return bool(scenario_policy.accepts(raw, question.canonical_answer))
    policy: Any = None
    if number == 6:
        from app.math.registry import ANSWER_POLICY_BY_SNAPSHOT

        policy = ANSWER_POLICY_BY_SNAPSHOT.get((family, policy_id, version))
    elif number == 7:
        from app.math.numbers import POLICY as policy7

        policy = policy7
    elif number == 9:
        from app.math.equations import ANSWER_POLICIES_BY_SNAPSHOT

        policy = ANSWER_POLICIES_BY_SNAPSHOT.get((policy_id, version))
    elif number == 11:
        from app.math.oge11 import POLICY_ID, POLICY_VERSION, parse_answer

        return (
            parse_answer(raw) == str(problem.get("correct_answer", ""))
            if (policy_id == POLICY_ID and version == POLICY_VERSION)
            else None
        )
    elif number == 13:
        selected = raw.strip()
        return (
            selected == str(problem.get("correct_answer", ""))
            if policy_id == "oge13.option-number" and version == "1"
            and selected in {"1", "2", "3", "4"}
            else None
        )
    else:
        from app.bot.training_engine import NUMERIC_TRAININGS

        numeric_adapter = NUMERIC_TRAININGS.get(number)
        policy = numeric_adapter.policy if numeric_adapter else None
    if policy is None or version != policy.version:
        return None
    if number != 9 and policy_id != policy.policy_id:
        return None
    parsed = policy.parse(raw)
    if parsed is None:
        return None
    if number == 7:
        if getattr(parsed, "denominator", None) != 1 or getattr(
            parsed, "numerator", 0
        ) not in range(1, 5):
            return None
    if number == 19 and parsed not in {"1", "2", "3"}:
        return None
    return bool(policy.accepts(raw, str(problem.get("correct_answer", ""))))


async def _issue(store: MixedTrainingRepository, user_id: int) -> dict[str, object] | None:
    expected = await store.expected_number(user_id)
    if expected is None:
        return None
    number, revision = expected
    state = await store.state(user_id)
    if state is None:
        return None
    session_state = state.get("state")
    generator_states = (
        cast(dict[str, object], session_state.get("generator_states", {}))
        if isinstance(session_state, dict)
        and isinstance(session_state.get("generator_states", {}), dict)
        else {}
    )
    saved_scenario = (
        session_state.get("scenario_snapshot") if isinstance(session_state, dict) else None
    )
    if 1 <= number <= 5:
        if isinstance(saved_scenario, dict):
            scenario = saved_scenario
        elif number == 1:
            try:
                scenario = await asyncio.to_thread(_scenario)
            except Exception as exc:
                raise _CandidateUnavailable("Could not generate OGE 1–5 scenario") from exc
        else:
            raise ValueError("Saved mixed scenario is missing during recovery")
        snapshot = await asyncio.to_thread(_scenario_question, scenario, number)
        return await store.issue_current(
            user_id,
            revision,
            number,
            snapshot,
            scenario_snapshot=(
                scenario if number == 1 and not isinstance(saved_scenario, dict) else None
            ),
        )
    number_state = generator_states.get(str(number))
    try:
        snapshot = await asyncio.to_thread(
            _candidate,
            number,
            cast(dict[str, object], number_state) if isinstance(number_state, dict) else None,
        )
    except Exception as exc:
        raise _CandidateUnavailable(f"Could not generate OGE {number}") from exc
    return await store.issue_current(user_id, revision, number, snapshot)


async def _send_problem(
    message: Message,
    repository: Repository,
    store: MixedTrainingRepository,
    problem: dict[str, object],
    *,
    user_id: int,
) -> None:
    number_value = problem.get("number")
    if not isinstance(number_value, int):
        raise ValueError("Mixed task number is invalid")
    number = number_value
    if number == 7:
        from app.math.oge07_validation import validate_task7_snapshot

        if not await asyncio.to_thread(validate_task7_snapshot, problem):
            raise ValueError("Mixed task 7 snapshot failed validation")
    elif number == 13:
        from app.math.inequalities import validate_snapshot as validate_inequality_snapshot

        if str(problem.get("family_id")) in {
            "OGE13-L01",
            "OGE13-Q01",
            "OGE13-Q02",
            "OGE13-Q03",
        } and not await asyncio.to_thread(validate_inequality_snapshot, problem):
            raise ValueError("Mixed task 13 snapshot failed validation")
    elif number == 19:
        from app.math.oge19 import validate_snapshot as validate_statement_snapshot

        runtime_fields = {
            "number",
            "outcome",
            "attempts",
            "hints_used",
            "prompt_message_id",
            "id",
            "record_id",
            "attempt_records",
            "issued_at",
        }
        statement_snapshot = {
            key: value for key, value in problem.items() if key not in runtime_fields
        }
        await asyncio.to_thread(validate_statement_snapshot, statement_snapshot)
    condition = str(problem.get("condition", ""))
    scenario: ScenarioSnapshot | None = None
    if number <= 5:
        raw_scenario = problem.get("scenario_snapshot")
        if not isinstance(raw_scenario, dict):
            raise ValueError("Mixed scenario snapshot is missing")
        scenario = await asyncio.to_thread(ScenarioSnapshot.from_snapshot, raw_scenario)
        await send_text(message, repository, scenario.shared_context, user_id_override=user_id)
    if number == 13:
        from app.bot.router import _task13_choice_text

        condition += "\n" + _task13_choice_text(problem)
    if number == 7:
        options = problem.get("options", [])
        if isinstance(options, list):
            condition += "\n\n" + "\n".join(
                f"{index}. {value}" for index, value in enumerate(options, 1)
            )
        condition += "\n\nВведите номер варианта 1–4."
    if number == 19:
        condition += "\n\nВведите номер верного утверждения: 1, 2 или 3."
    elif number == 11:
        condition += "\n\nВведите три цифры в порядке А, Б, В. Используйте 1, 2 и 3 по одному разу."
    elif number not in {7, 13}:
        condition += (
            "\n\nНапишите ответ числом в чат. Дробную часть можно отделять запятой или точкой."
        )
    photos = (
        await asyncio.to_thread(scenario_photos_for_question, scenario, number)
        if scenario is not None
        else ()
    )
    if photos:
        for photo_bytes in photos:
            await send_photo(
                message,
                repository,
                BufferedInputFile(photo_bytes, filename="scenario.png"),
                caption=f"Данные задачи №{number}",
                user_id_override=user_id,
            )
    image_data = (
        None if number <= 5 else await asyncio.to_thread(_render_image, number, problem)
    )
    completed = problem.get("outcome") in {"solved", "failed", "skipped", "solution_viewed"}
    markup = _mixed_menu(
        str(problem["problem_id"]),
        completed=completed,
        choices=0 if completed else (3 if number == 19 else (4 if number == 13 else 0)),
    )
    caption = f"Задание №{number}\n\n{condition}"
    if image_data is not None:
        sent = await send_photo(
            message,
            repository,
            BufferedInputFile(image_data, filename=f"oge{number}.png"),
            caption=caption,
            reply_markup=markup,
            user_id_override=user_id,
        )
    else:
        sent = await send_text(
            message, repository, caption, reply_markup=markup, user_id_override=user_id
        )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await store.set_prompt(user_id, str(problem["problem_id"]), prompt_id)


async def start_mixed(message: Message, repository: Repository) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    store = MixedTrainingRepository(repository)
    await store.start(user_id, available_numbers())
    session = await store.state(user_id)
    current = session.get("problem") if session else None
    if not isinstance(current, dict):
        try:
            current = await _issue(store, user_id)
        except _CandidateUnavailable:
            await send_text(
                message,
                repository,
                "Не удалось подготовить задание. Смешанная тренировка сохранена; "
                "нажмите «Продолжить», чтобы повторить попытку.",
                reply_markup=main_menu(has_session=True),
                user_id_override=user_id,
            )
            return
    if not isinstance(current, dict):
        await send_text(
            message,
            repository,
            "Не удалось открыть смешанную тренировку.",
            reply_markup=main_menu(),
        )
        return
    await _send_problem(message, repository, store, current, user_id=user_id)


async def continue_mixed(message: Message, repository: Repository, user_id: int) -> bool:
    store = MixedTrainingRepository(repository)
    await store.start(user_id, available_numbers())
    state = await store.state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict):
        try:
            problem = await _issue(store, user_id)
        except _CandidateUnavailable:
            await send_text(
                message,
                repository,
                "Не удалось подготовить задание. Смешанная тренировка сохранена; "
                "нажмите «Продолжить», чтобы повторить попытку.",
                reply_markup=main_menu(has_session=True),
                user_id_override=user_id,
            )
            return True
    if not isinstance(problem, dict):
        return False
    await _send_problem(message, repository, store, problem, user_id=user_id)
    return True


async def mixed_answer(message: Message, repository: Repository) -> None:
    if message.from_user is None or message.text is None:
        return
    user_id = message.from_user.id
    if await repository.user_state(user_id) != "mixed":
        raise SkipHandler
    store = MixedTrainingRepository(repository)
    state = await store.state(user_id)
    if state is None:
        return
    problem = state.get("problem")
    if not isinstance(problem, dict) or problem.get("outcome") != "issued":
        await send_text(message, repository, "Откройте активное задание смешанной тренировки.")
        return
    session = state.get("state")
    prompt_id = problem.get("prompt_message_id")
    if isinstance(session, dict) and not matches_current_condition(
        message, {"problem_prompt_message_id": prompt_id}
    ):
        return
    task_number = problem.get("number")
    if not isinstance(task_number, int):
        return
    correct = await asyncio.to_thread(_is_correct, task_number, problem, message.text)
    if correct is None:
        await send_text(message, repository, "Ответ не соответствует формату этого задания.")
        return
    result = await store.answer(
        user_id,
        str(problem["problem_id"]),
        message.text,
        correct,
        message.message_id,
        message.reply_to_message.message_id if message.reply_to_message else None,
    )
    if result is None or result.get("status") in {"stale", "duplicate"}:
        return
    updated = cast(dict[str, object], result.get("problem", problem))
    status = str(result.get("status"))
    if status == "active":
        text = "Пока неверно. Попробуйте ещё раз."
    elif status == "solved":
        text = "✅ Верно! Ответ засчитан."
    elif status == "failed":
        text = (
            f"Вторая попытка неверна. Ответ: {updated.get('correct_answer')}\n\nРазбор:\n"
            + "\n".join(_string_list(updated.get("solution")))
        )
    else:
        return
    sent = await send_text(
        message,
        repository,
        text,
        reply_markup=_mixed_menu(
            str(problem["problem_id"]),
            completed=status != "active",
            choices=3
            if int(problem["number"]) == 19
            else (4 if int(problem["number"]) == 13 else 0),
        ),
        user_id_override=user_id,
    )
    prompt = getattr(sent, "message_id", None)
    if type(prompt) is int:
        await store.set_prompt(user_id, str(problem["problem_id"]), prompt)


async def mixed_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":")
    if (
        len(parts) not in {3, 4}
        or parts[0] != "mixed"
        or not isinstance(callback.message, Message)
    ):
        await answer_callback(callback)
        return
    message = callback.message
    _, action, problem_id = parts[:3]
    user_id = callback.from_user.id
    store = MixedTrainingRepository(repository)
    state = await store.state(user_id)
    if state is None:
        await answer_callback(callback, "Смешанная тренировка не найдена.")
        return
    problem = state.get("problem")
    if await repository.user_state(user_id) != "mixed":
        await answer_callback(callback, "Смешанная тренировка приостановлена.")
        return
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != problem_id:
        await answer_callback(callback, "Это задание уже сменилось.")
        return
    number_value = problem.get("number")
    if not isinstance(number_value, int):
        await answer_callback(callback, "Сохранённое задание повреждено.")
        return
    number = number_value
    if action == "pick" and len(parts) == 4:
        if parts[3] not in {"1", "2", "3", "4"}:
            await answer_callback(callback, "Этот вариант недоступен.")
            return
        correct = await asyncio.to_thread(_is_correct, number, problem, parts[3])
        if correct is None:
            await answer_callback(callback, "Этот вариант недоступен.")
            return
        result = await store.answer(
            user_id,
            problem_id,
            parts[3],
            correct,
            _callback_dedupe_id(callback),
            message.message_id,
        )
        status = str(result.get("status")) if result else "stale"
        if status not in {"active", "solved", "failed"}:
            await answer_callback(callback, "Ответ уже обработан.")
            return
        updated = cast(dict[str, object], result.get("problem", problem)) if result else problem
        if status == "active":
            body = "Пока неверно. Попробуйте ещё раз."
        elif status == "solved":
            body = "✅ Верно! Ответ засчитан."
        else:
            body = (
                f"Вторая попытка неверна. Ответ: {updated.get('correct_answer')}\n\nРазбор:\n"
                + "\n".join(_string_list(updated.get("solution")))
            )
        await send_text(
            message,
            repository,
            body,
            reply_markup=_mixed_menu(
                problem_id,
                completed=status != "active",
                choices=3 if number == 19 else (4 if number == 13 else 0),
            ),
            user_id_override=user_id,
        )
        await answer_callback(callback)
        return
    if action == "menu":
        await store.pause(user_id)
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Тренировка сохранена.",
            reply_markup=main_menu(has_session=True),
            user_id_override=user_id,
        )
        await answer_callback(callback)
        return
    if action == "hint":
        ok = await store.action(user_id, problem_id, "hint")
        refreshed = await store.state(user_id)
        actual = refreshed.get("problem") if refreshed else None
        hints = actual.get("hints", []) if isinstance(actual, dict) else []
        used_value = actual.get("hints_used", 0) if isinstance(actual, dict) else 0
        used = used_value if isinstance(used_value, int) else 0
        hint = hints[used - 1] if ok and isinstance(hints, list) and used else None
        if hint:
            await send_text(message, repository, hint_message(str(hint), problem))
        else:
            await send_text(message, repository, "Подсказок больше нет.")
        await answer_callback(callback)
        return
    if action == "solution":
        await store.action(user_id, problem_id, "solution")
        text = (
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(str(item) for item in problem.get("solution", []))
            + f"\n\nОтвет: {problem.get('correct_answer')}"
        )
        await send_text(
            message,
            repository,
            text,
            reply_markup=_mixed_menu(problem_id, completed=True),
            user_id_override=user_id,
        )
        await answer_callback(callback)
        return
    if action not in {"next", "skip"}:
        await answer_callback(callback)
        return
    if action == "skip":
        await store.action(user_id, problem_id, "skip")
    state_data_raw = state.get("state", {}) if state else {}
    state_data = cast(dict[str, object], state_data_raw) if isinstance(state_data_raw, dict) else {}
    queue = state_data.get("queue", [])
    if (
        state_data.get("scenario_snapshot") is not None
        and isinstance(state_data.get("scenario_position", 1), int)
        and cast(int, state_data.get("scenario_position", 1)) < 5
    ):
        result = await store.advance(user_id, problem_id, None, None)
    else:
        next_numbers = _number_list(queue)
        if not next_numbers:
            next_numbers = _number_list(state_data.get("available_numbers", []))
            secrets.SystemRandom().shuffle(next_numbers)
            last = number
            if len(next_numbers) > 1 and next_numbers[0] == last:
                next_numbers[0], next_numbers[1] = next_numbers[1], next_numbers[0]
        next_number = int(next_numbers[0]) if next_numbers else None
        try:
            scenario = await asyncio.to_thread(_scenario) if next_number == 1 else None
        except Exception:
            await send_text(
                message,
                repository,
                "Не удалось подготовить следующее задание. Занятие сохранено; "
                "нажмите «Следующее» под завершённым заданием для повтора.",
                reply_markup=main_menu(has_session=True),
                user_id_override=user_id,
            )
            await answer_callback(callback, "Повторите переход кнопкой под заданием.")
            return
        generator_states = state_data.get("generator_states", {})
        number_state = (
            generator_states.get(str(next_number))
            if isinstance(generator_states, dict) and next_number is not None
            else None
        )
        try:
            snapshot = (
                await asyncio.to_thread(_scenario_question, scenario, 1)
                if scenario
                else await asyncio.to_thread(
                    _candidate,
                    next_number,
                    cast(dict[str, object], number_state)
                    if isinstance(number_state, dict)
                    else None,
                )
                if next_number
                else None
            )
        except Exception:
            await send_text(
                message,
                repository,
                "Не удалось подготовить следующее задание. Занятие сохранено; "
                "нажмите «Следующее» под завершённым заданием для повтора.",
                reply_markup=main_menu(has_session=True),
                user_id_override=user_id,
            )
            await answer_callback(callback, "Повторите переход кнопкой под заданием.")
            return
        result = await store.advance(
            user_id,
            problem_id,
            snapshot,
            next_number,
            new_cycle=next_numbers,
            scenario_snapshot=scenario,
        )
    if not isinstance(result, dict):
        await answer_callback(callback, "Тренировка завершена.")
        return
    if result.get("outcome") == "issued" and isinstance(result.get("problem_id"), str):
        await _send_problem(message, repository, store, result, user_id=user_id)
        await answer_callback(callback)
        return
    pending = result.get("pending_snapshot")
    number_value = result.get("number")
    expected_revision = result.get("expected_revision")
    if not isinstance(number_value, int) or not isinstance(expected_revision, int):
        await answer_callback(callback, "Смешанная очередь повреждена.")
        return
    number = number_value
    if not isinstance(pending, dict):
        try:
            issued = await _issue(store, user_id)
        except _CandidateUnavailable:
            await send_text(
                message,
                repository,
                "Не удалось подготовить следующее задание. Смешанное занятие сохранено; "
                "нажмите «Продолжить» для безопасного повтора.",
                reply_markup=main_menu(has_session=True),
                user_id_override=user_id,
            )
            await answer_callback(callback, "Занятие сохранено")
            return
        if not isinstance(issued, dict):
            await answer_callback(callback, "Задание уже было открыто.")
            return
        await _send_problem(message, repository, store, issued, user_id=user_id)
        await answer_callback(callback)
        return
    issued = await store.issue_current(
        user_id,
        expected_revision,
        number,
        pending,
        scenario_snapshot=cast(dict[str, object], result.get("scenario_snapshot"))
        if number == 1 and isinstance(result.get("scenario_snapshot"), dict)
        else None,
    )
    if not isinstance(issued, dict):
        await answer_callback(callback, "Задание уже было открыто.")
        return
    await _send_problem(message, repository, store, issued, user_id=user_id)
    await answer_callback(callback)
