"""Build PR #113 offline payload evidence and the linked visual acceptance gallery."""

# Imports follow workspace path setup; generated matrix evidence has intentionally long labels.
# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import BufferedInputFile, Chat, InlineKeyboardMarkup, Message, PhotoSize, User

from app.bot import adaptive, error_replay, mixed_training, progress, scenario_training
from app.bot.bop_copy import reply
from app.bot.math_layout import question_message, solution_message
from app.bot.presentation import hint_message, send_text
from app.bot.progress_image import progress_image_keyboard, render_progress_image
from app.bot.scenario_materials import send_scenario_materials
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.ROUTE import build_adapter as build_route_adapter
from app.persistence.scenario_repository import ScenarioPostgresRepository, ScenarioSession

PUBLIC_STORIES = ("TYRES", "PAPER", "STOVE", "TARIFF", "GARDEN", "FLAT")
VIEWPORTS = (360, 390, 430)
STORY_MATRIX = ROOT / "reports" / "scenario-material-coverage.csv"
OUT = ROOT / "reports" / "pr113-visual-acceptance"


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"pr113-visual-acceptance:{name}")


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump(mode="json", exclude_none=True))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class OfflineCaptureSession(BaseSession):
    """Offline aiogram transport that serializes the actual Bot API method objects."""

    def __init__(self, case_id: str) -> None:
        super().__init__()
        self.case_id = case_id
        self.calls: list[dict[str, Any]] = []
        self.message_id = 0

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):
        if False:
            yield b""

    async def make_request(  # noqa: ASYNC109 (aiogram BaseSession interface)
        self,
        bot: Bot,
        method: Any,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> Message:
        self.message_id += 1
        method_name = str(getattr(method, "__api_method__", type(method).__name__))
        call: dict[str, Any] = {"sequence": len(self.calls) + 1, "method": method_name}
        scalar_fields = (
            "chat_id",
            "message_thread_id",
            "text",
            "caption",
            "parse_mode",
            "disable_notification",
            "protect_content",
        )
        for field in scalar_fields:
            value = getattr(method, field, None)
            if value is not None:
                call[field] = json_safe(value)

        markup = getattr(method, "reply_markup", None)
        if markup is not None:
            call["reply_markup"] = json_safe(markup)
        rich = getattr(method, "rich_message", None)
        if rich is not None:
            call["rich_message"] = {
                "html": str(getattr(rich, "html", "")),
                "media": json_safe(getattr(rich, "media", None)),
            }

        media_items = []
        photo = getattr(method, "photo", None)
        if isinstance(photo, BufferedInputFile):
            media_items.append((photo.filename or "photo.png", photo.data))
        if rich is not None:
            for item in getattr(rich, "media", None) or ():
                source = getattr(getattr(item, "media", None), "media", None)
                if isinstance(source, BufferedInputFile):
                    media_items.append((source.filename or "rich-media.png", source.data))
        saved_media = []
        for original_name, data in media_items:
            digest = hashlib.sha256(data).hexdigest()
            relative = f"assets/png/{digest}.png"
            target = OUT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
            saved_media.append(
                {
                    "file": relative,
                    "source_filename": original_name,
                    "sha256": digest,
                    "bytes": len(data),
                }
            )
        if saved_media:
            call["media"] = saved_media
        self.calls.append(call)

        return Message(
            message_id=self.message_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=123456, is_bot=True, first_name="Offline preview"),
            photo=[
                PhotoSize(
                    file_id=f"offline-{self.message_id}",
                    file_unique_id="offline",
                    width=1,
                    height=1,
                )
            ]
            if method_name == "sendPhoto"
            else None,
        ).as_(bot)


class OfflineRepository:
    """Synthetic repository surface needed by the presentation helpers."""

    async def math_display(self, user_id: int | None, template_id: str | None = None) -> str:
        return "rich"

    async def set_navigation_message(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def claim_navigation_message(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def personal_enabled(self, user_id: int) -> bool:
        return True

    async def save_user_state(self, *args: Any, **kwargs: Any) -> None:
        return None


def api_card(call: dict[str, Any]) -> str:
    method = str(call.get("method", ""))
    rich = call.get("rich_message")
    if isinstance(rich, dict):
        body = str(rich.get("html", ""))
    else:
        body = str(call.get("text") or call.get("caption") or "")
    images = "".join(
        f'<img class="payload-image" src="{html.escape(item["file"])}" '
        f'alt="Изображение из sendPhoto payload">'
        for item in call.get("media", [])
    )
    buttons = []
    markup = call.get("reply_markup")
    if isinstance(markup, dict):
        for row in markup.get("inline_keyboard", []):
            for button in row:
                if isinstance(button, dict):
                    buttons.append(str(button.get("text", "")))
    keyboard = (
        '<div class="keyboard">'
        + "".join(f"<span>{html.escape(label)}</span>" for label in buttons)
        + "</div>"
        if buttons
        else ""
    )
    raw = html.escape(json.dumps(call, ensure_ascii=False, indent=2))
    media_links = "".join(
        f'<a href="{html.escape(item["file"])}">PNG · {html.escape(item["sha256"][:12])}</a>'
        for item in call.get("media", [])
    )
    return (
        f'<article class="payload"><small>{call.get("sequence", "?")} · '
        f'{html.escape(method)}</small><div class="bubble">{body}</div>{keyboard}{images}'
        f"{media_links}<details><summary>Сериализованный запрос Bot API</summary>"
        f"<pre>{raw}</pre></details></article>"
    )


def payload_case(
    case_id: str, label: str, category: str, calls: list[dict[str, Any]], **meta: Any
) -> dict[str, Any]:
    record = {"id": case_id, "label": label, "category": category, **meta, "calls": calls}
    target = OUT / "payloads" / f"{case_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for call in calls:
        rich = call.get("rich_message")
        if isinstance(rich, dict) and rich.get("html"):
            rich_path = OUT / "payloads" / "rich" / f"{case_id}-{call['sequence']:02}.html"
            rich_path.parent.mkdir(parents=True, exist_ok=True)
            rich_path.write_text(str(rich["html"]), encoding="utf-8")
    return record


async def capture_case(case_id: str, action) -> list[dict[str, Any]]:
    session = OfflineCaptureSession(case_id)
    bot = Bot("123456:OFFLINE", session=session)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Synthetic learner"),
    ).as_(bot)
    await action(message, OfflineRepository())
    calls = list(session.calls)
    await bot.session.close()
    return calls


async def render_scenario(
    snapshot: ScenarioSnapshot,
    position: int,
    case_id: str,
    *,
    mode: PracticeMode,
    show_assets: bool = True,
    show_current_asset: bool = False,
    status: str = "active",
    result_text: Any = None,
) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        store = AsyncMock(spec=ScenarioPostgresRepository)
        store.close_legacy_with_exposed_answer.return_value = False
        state = ScenarioSession(
            uid(case_id),
            uid(case_id + ":scenario"),
            mode,
            "active",
            position,
            0,
            status,
            0,
            0,
            None,
            None,
            snapshot,
        )
        await scenario_training.render_session(
            message,
            store,
            state,
            show_assets=show_assets,
            show_current_asset=show_current_asset,
            result_text=result_text,
            user_id_override=42,
            repository=repository,
        )

    return await capture_case(case_id, action)


async def render_mixed(
    snapshot: ScenarioSnapshot, position: int, case_id: str
) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
        problem["number"] = position
        store = AsyncMock()
        store.set_prompt.return_value = True
        await mixed_training._send_problem(message, repository, store, problem, user_id=42)

    return await capture_case(case_id, action)


async def render_replay(
    snapshot: ScenarioSnapshot, position: int, case_id: str
) -> list[dict[str, Any]]:
    from app.persistence.error_replay import ReplaySource

    async def action(message: Message, repository: OfflineRepository) -> None:
        problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
        replay_id = uid(case_id)
        source = ReplaySource(
            "scenario",
            uid(case_id + ":source"),
            position,
            position,
            problem,
            snapshot.to_snapshot(),
        )
        store = AsyncMock()
        await error_replay._render(
            message,
            repository,
            store,
            {"id": str(replay_id), "status": "active", "attempt_count": 1},
            source,
            user_id=42,
            materials=error_replay._materials(source),
        )

    return await capture_case(case_id, action)


async def render_personal(
    snapshot: ScenarioSnapshot, position: int, case_id: str
) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
        row = {
            "problem": case_id,
            "id": uid(case_id),
            "position": 0,
            "outcome": "issued",
            "hints_used": 0,
            "prompt": None,
            "snapshot": json.dumps(problem, ensure_ascii=False),
            "plan": json.dumps([problem["family_id"]]),
        }
        await send_scenario_materials(
            message,
            repository,
            snapshot,
            position,
            user_id=42,
        )
        body = question_message(
            "Персональная тренировка",
            problem["condition"],
            "Напиши ответ в чат.",
        )
        await send_text(
            message,
            repository,
            body,
            reply_markup=adaptive.keyboard(row),
            user_id_override=42,
            math_family=problem,
        )

    return await capture_case(case_id, action)


async def render_material_reopen(
    snapshot: ScenarioSnapshot, position: int, case_id: str
) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        await send_scenario_materials(message, repository, snapshot, position, user_id=42)

    return await capture_case(case_id, action)


async def render_feedback(body: Any, case_id: str) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        await send_text(message, repository, body, user_id_override=42)

    return await capture_case(case_id, action)


async def render_short_strategy(
    snapshot: ScenarioSnapshot,
    position: int,
    case_id: str,
    strategy: str,
) -> list[dict[str, Any]]:
    async def action(message: Message, repository: OfflineRepository) -> None:
        problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
        problem["number"] = position
        row = {
            "id": uid(case_id),
            "position": 0,
            "strategy": strategy,
            "problem": case_id,
            "prompt": None,
            "snapshot": json.dumps(problem, ensure_ascii=False),
            "plan": json.dumps([problem["family_id"]]),
            "scope": {"number": position, "plan_seed": "gallery-seed"},
            "outcome": "issued",
            "hints_used": 0,
            "revision": 3,
        }
        store = AsyncMock()
        store.current.return_value = row
        store.excluded_for_learner.return_value = []
        previous = adaptive.Session
        previous_inputs = adaptive._learner_inputs
        previous_select = adaptive._select
        adaptive.Session = lambda _repository, _learner: store
        adaptive._learner_inputs = AsyncMock(return_value=([], {}))
        adaptive._select = (
            lambda _strategy, _learner, _history, _insights, **kwargs: SimpleNamespace(
                slots=[problem["family_id"]],
                reasons=(),
            )
        )
        try:
            await adaptive.present(message, repository, 42)
        finally:
            adaptive.Session = previous
            adaptive._learner_inputs = previous_inputs
            adaptive._select = previous_select

    return await capture_case(case_id, action)


def write_png_asset(data: bytes, original_name: str) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    relative = f"assets/png/{digest}.png"
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return {
        "file": relative,
        "source_filename": original_name,
        "sha256": digest,
        "bytes": len(data),
    }


def build_progress_insights() -> dict[str, Any]:
    return {
        "total": {"correct": 8, "answered_tasks": 10, "issued": 12, "skipped": 1},
        "numbers": {
            1: {
                "correct": 3,
                "answered_tasks": 4,
                "first_correct": 2,
                "second_correct": 1,
                "assisted_correct": 1,
                "unassisted_correct": 2,
                "skipped": 0,
            },
            15: {
                "correct": 5,
                "answered_tasks": 6,
                "first_correct": 3,
                "second_correct": 2,
                "assisted_correct": 2,
                "unassisted_correct": 3,
                "skipped": 1,
            },
        },
        "families": [
            {
                "number": 1,
                "family_id": "TYRES-SIDEWALL",
                "name": "Высота боковины",
                "answered_tasks": 2,
                "correct": 1,
                "first_correct": 1,
                "second_correct": 0,
                "assisted_correct": 1,
                "unassisted_correct": 0,
                "practice_priority": True,
                "diagnosis_key": "gap",
            },
            {
                "number": 1,
                "family_id": "TYRES-DIAMETER",
                "name": "Диаметр колеса",
                "answered_tasks": 2,
                "correct": 2,
                "first_correct": 1,
                "second_correct": 1,
                "assisted_correct": 0,
                "unassisted_correct": 2,
                "practice_priority": False,
                "diagnosis_key": "confirmed",
            },
            {
                "number": 15,
                "family_id": "OGE15-R01",
                "name": "Площади по плану",
                "answered_tasks": 2,
                "correct": 1,
                "first_correct": 1,
                "second_correct": 0,
                "assisted_correct": 1,
                "unassisted_correct": 0,
                "practice_priority": True,
                "diagnosis_key": "check",
            },
        ],
        "personal_tip": "Проверь вычисление площади по плану.",
        "history": [],
        "errors": [],
        "page_total": 0,
    }


async def generate(output: Path) -> None:
    global OUT
    OUT = output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "payloads").mkdir(exist_ok=True)
    (OUT / "assets" / "png").mkdir(parents=True, exist_ok=True)
    registry = scenario_training.public_registry()
    coverage = list(csv.DictReader(STORY_MATRIX.open(encoding="utf-8-sig")))
    cases: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    material_rows: list[dict[str, Any]] = []

    def record(
        case_id: str, label: str, category: str, calls: list[dict[str, Any]], **meta: Any
    ) -> None:
        cases.append(payload_case(case_id, label, category, calls, **meta))

    # Complete five-position runs for all six public narratives.
    full_snapshots: dict[str, ScenarioSnapshot] = {}
    for story in PUBLIC_STORIES:
        snap = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, 42, story),
            registry,
        ).snapshot
        full_snapshots[story] = snap
        for position in range(1, 6):
            case_id = f"full-{story.lower()}-q{position}"
            calls = await render_scenario(
                snap,
                position,
                case_id,
                mode=PracticeMode.FULL,
            )
            record(
                case_id,
                f"Полный комплект · {story} · вопрос {position}",
                "full-scenario",
                calls,
                story=story,
                seed=42,
                position=position,
                mode="full",
            )

    # Single mode, one actual render_session call sequence per all 40 public families.
    for row in coverage:
        story = row["story"]
        seed = int(row["seed"])
        position = int(row["position"])
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.SINGLE, seed, story, position),
            registry,
        )
        question = plan.snapshot.questions[position - 1]
        if question.family_id != row["family"]:
            raise ValueError(f"Coverage row mismatch: {row['family']} != {question.family_id}")
        case_id = f"single-{question.family_id.lower()}"
        calls = await render_scenario(
            plan.snapshot,
            position,
            case_id,
            mode=PracticeMode.SINGLE,
        )
        record(
            case_id,
            f"Одиночная выдача · {question.family_id}",
            "single-family",
            calls,
            story=story,
            seed=seed,
            position=position,
            family=question.family_id,
            mode="single",
        )
        family_rows.append(
            {
                "family_id": question.family_id,
                "status": "public-enabled",
                "story": story,
                "seed": seed,
                "position": position,
                "example": f"payloads/{case_id}.json",
            }
        )
        material_rows.append(
            {
                "family_id": question.family_id,
                "story": story,
                "seed": seed,
                "position": position,
                "modes": row["paths"],
                "evidence": row["evidence"],
                "payload": f"payloads/{case_id}.json",
            }
        )

    # Personal adaptive and mixed delivery use the same GARDEN world and true app render helpers.
    personal_snap = full_snapshots["GARDEN"]
    personal_calls = await render_personal(personal_snap, 3, "personal-garden-q3")
    record(
        "personal-garden-q3",
        "Персональная тренировка · GARDEN №3",
        "personal-training",
        personal_calls,
        story="GARDEN",
        seed=42,
        position=3,
    )
    mixed_calls = await render_mixed(personal_snap, 3, "mixed-garden-q3")
    record(
        "mixed-garden-q3",
        "Смешанная тренировка · GARDEN №3",
        "mixed-training",
        mixed_calls,
        story="GARDEN",
        seed=42,
        position=3,
    )
    for strategy in ("personal", "mixed", "number", "family"):
        short_id = f"short-{strategy}-garden-q3"
        short_calls = await render_short_strategy(personal_snap, 3, short_id, strategy)
        record(
            short_id,
            f"Короткая тренировка · {strategy} · GARDEN №3",
            "short-training",
            short_calls,
            story="GARDEN",
            seed=42,
            position=3,
            strategy=strategy,
            route="adaptive.present",
        )

    # Resume/reopen data, hints, worked solution, correctness feedback and the second-error state.
    scene = full_snapshots["FLAT"]
    q = scene.questions[2]
    reopen_calls = await render_material_reopen(scene, 3, "reopen-flat-q3")
    record(
        "reopen-flat-q3",
        "Повторное открытие схемы и данных · FLAT №3",
        "data-reopen",
        reopen_calls,
        story="FLAT",
        seed=42,
        position=3,
    )

    hint_calls = await render_feedback(
        hint_message(q.hints[0], {"hints": q.hints}),
        "hint-flat-q3",
    )
    record(
        "hint-flat-q3", "Подсказка · FLAT №3", "hint", hint_calls, story="FLAT", seed=42, position=3
    )
    solution_calls = await render_feedback(
        solution_message(q.solution_steps, q.canonical_answer),
        "solution-flat-q3",
    )
    record(
        "solution-flat-q3",
        "Разбор · FLAT №3",
        "solution",
        solution_calls,
        story="FLAT",
        seed=42,
        position=3,
    )

    correct_calls = await render_feedback(reply("correct", 0), "correct-flat-q3")
    record(
        "correct-flat-q3",
        "Верный ответ · FLAT №3",
        "answer-correct",
        correct_calls,
        story="FLAT",
        seed=42,
        position=3,
    )
    wrong_calls = await render_feedback(reply("wrong", 1), "wrong-flat-q3")
    record(
        "wrong-flat-q3",
        "Ошибка · первая попытка · FLAT №3",
        "answer-wrong",
        wrong_calls,
        story="FLAT",
        seed=42,
        position=3,
    )
    second_error = solution_message(q.solution_steps, q.canonical_answer, reply("review", 2))
    second_calls = await render_feedback(second_error, "second-error-flat-q3")
    record(
        "second-error-flat-q3",
        "Ошибка · вторая попытка · FLAT №3",
        "answer-second-error",
        second_calls,
        story="FLAT",
        seed=42,
        position=3,
    )

    # Session result and progress screens use app TrainingMessage/progress renderers and keyboards.
    async def capture_ui_text(
        case_id: str,
        body: Any,
        markup: InlineKeyboardMarkup | None = None,
        *,
        math_family: Any = None,
    ) -> list[dict[str, Any]]:
        async def action(message: Message, repository: OfflineRepository) -> None:
            await send_text(
                message,
                repository,
                body,
                reply_markup=markup,
                user_id_override=42,
                math_family=math_family,
            )

        return await capture_case(case_id, action)

    async def completion_action(message: Message, repository: OfflineRepository) -> None:
        store = AsyncMock()
        store.summary_deltas.return_value = {}
        store.totals.return_value = {
            "solved": 4,
            "issued": 5,
            "independent": 3,
            "skipped": 1,
            "completed": 5,
        }
        store.learner = 42
        repository.personal_enabled = AsyncMock(return_value=False)
        await adaptive.completion(
            message, repository, store, {"id": uid("completion")}, "Тренировка завершена!"
        )

    result_calls = await capture_case("training-summary", completion_action)
    record("training-summary", "Итоги тренировки", "training-result", result_calls, mode="full")

    insights = build_progress_insights()
    progress_cases = [
        (
            "progress-summary",
            "Общий прогресс",
            "summary",
            progress.progress_keyboard("summary", insights=insights),
        ),
        (
            "progress-details",
            "Детализация по номеру",
            "details",
            progress.progress_keyboard("details", insights=insights),
        ),
        (
            "progress-number-15",
            "Мой прогресс · №15",
            "number:15",
            progress.progress_keyboard("number:15", number=15, family_total=1, insights=insights),
        ),
        (
            "progress-family-15",
            "Сводка по типам · №15",
            "family:15:0",
            progress.progress_keyboard("family:15:0", number=15, family_total=1, insights=insights),
        ),
    ]
    for case_id, label, page, markup in progress_cases:
        calls = await capture_ui_text(case_id, progress.render_progress(insights, page), markup)
        record(case_id, label, "progress", calls, page=page)

    # Actual dashboard PNG bytes from the same renderer used by the progress screen.
    dashboard_bytes = render_progress_image({**insights, "display_identity": "Synthetic learner"})

    async def dashboard_action(message: Message, repository: OfflineRepository) -> None:
        from aiogram.types import BufferedInputFile

        from app.bot.presentation import send_photo

        markup = progress_image_keyboard(insights)
        await send_photo(
            message,
            repository,
            BufferedInputFile(dashboard_bytes, filename="progress.png"),
            caption="Мой прогресс",
            user_id_override=42,
            reply_markup=markup,
        )

    record(
        "progress-dashboard-png",
        "Визуальный общий прогресс · PNG",
        "progress-image",
        await capture_case("progress-dashboard-png", dashboard_action),
        page="summary",
    )

    # History replay traverses error_replay._render with a synthetic immutable source snapshot.
    replay_snapshot = full_snapshots["TYRES"]
    replay_calls = await render_replay(replay_snapshot, 1, "error-replay-tyres-q1")
    record(
        "error-replay-tyres-q1",
        "Повтор ошибки из истории · TYRES №1",
        "error-replay",
        replay_calls,
        story="TYRES",
        seed=42,
        position=1,
    )

    # Closed ROUTE sample is generated from its private adapter only; never sent via the router.
    route_adapter = build_route_adapter()
    route_scenario = route_adapter.generator.generate_scenario(42)
    route_rendered = route_adapter.renderer.render_scenario(route_scenario)
    route_snapshot = ScenarioSnapshot(
        story_code=route_scenario.story_code,
        seed=route_scenario.seed,
        generator_version=route_scenario.generator_version,
        compatibility_matrix_version=route_scenario.compatibility_matrix_version,
        context=route_scenario.context,
        shared_context=route_rendered.shared_context,
        assets=route_rendered.assets,
        questions=tuple(
            __import__(
                "app.math.scenario_engine", fromlist=["QuestionSnapshot"]
            ).QuestionSnapshot.from_draft(
                route_adapter.question_builder.build_question(route_scenario, p)
            )
            for p in range(1, 6)
        ),
        provenance=route_scenario.provenance,
    )
    route_assets = [
        write_png_asset(
            restore_asset_bytes(route_adapter.renderer, route_snapshot, asset),
            f"route-seed-42.{asset.content_type.rsplit('/', 1)[-1]}",
        )
        for asset in route_snapshot.assets
        if asset.content_type == "image/png"
    ]
    route_svg = next(
        (
            restore_asset_bytes(route_adapter.renderer, route_snapshot, asset)
            for asset in route_snapshot.assets
            if asset.content_type == "image/svg+xml"
        ),
        b"",
    )
    route_svg_hash = hashlib.sha256(route_svg).hexdigest()
    route_svg_path = f"assets/svg/{route_svg_hash}.svg"
    (OUT / route_svg_path).parent.mkdir(parents=True, exist_ok=True)
    (OUT / route_svg_path).write_bytes(route_svg)
    route_doc = {
        "status": "closed-disabled",
        "public": False,
        "telegram_route": False,
        "prototype_mismatch": "GRID-4 is synthetic; original raster not available for visual audit.",
        "story": "ROUTE",
        "seed": 42,
        "shared_prompt": route_snapshot.shared_context,
        "questions": [q.condition for q in route_snapshot.questions],
        "assets": route_assets
        + [{"file": route_svg_path, "content_type": "image/svg+xml", "sha256": route_svg_hash}],
    }
    (OUT / "closed-route.json").write_text(
        json.dumps(route_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    family_rows.extend(
        {
            "family_id": item.family_id,
            "status": "closed-disabled",
            "story": "ROUTE",
            "seed": 42,
            "position": index,
            "example": "closed-route.json",
        }
        for index, item in enumerate(route_adapter.family_registry, 1)
    )

    # Matrix every family together with the source mode matrix from the audited report.
    with (OUT / "family-matrix.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=("family_id", "status", "story", "seed", "position", "example")
        )
        writer.writeheader()
        writer.writerows(family_rows)
    with (OUT / "material-modes.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=("family_id", "story", "seed", "position", "modes", "evidence", "payload"),
        )
        writer.writeheader()
        writer.writerows(material_rows)

    (OUT / "api-calls.json").write_text(
        json.dumps(
            [
                {
                    "id": case["id"],
                    "label": case["label"],
                    "category": case["category"],
                    "calls": case["calls"],
                }
                for case in cases
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_gallery(cases, route_doc, family_rows)
    write_readme_and_route_matrix(cases, coverage)
    print(
        json.dumps(
            {
                "output": str(OUT),
                "public_family_count": len(coverage),
                "route_family_count": len(route_adapter.family_registry),
                "family_count": len(family_rows),
                "full_story_count": len(PUBLIC_STORIES),
                "case_count": len(cases),
                "png_count": len(list((OUT / "assets" / "png").glob("*.png"))),
                "api_call_count": sum(len(case["calls"]) for case in cases),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_gallery(
    cases: list[dict[str, Any]], route: dict[str, Any], families: list[dict[str, Any]]
) -> None:
    ids_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        ids_by_category[case["category"]].append(case)
    titles = {
        "full-scenario": "1. Полные комплекты №1–5 публичных сюжетов",
        "single-family": "2. Одиночная выдача 40 публичных семейств",
        "personal-training": "3. Персональная тренировка",
        "mixed-training": "3. Смешанная тренировка",
        "short-training": "3. Короткие тренировки · personal / mixed / number / family",
        "data-reopen": "4. Повторное открытие схемы и данных",
        "hint": "5. Подсказка",
        "solution": "5. Разбор",
        "answer-correct": "6. Верный ответ",
        "answer-wrong": "6. Первая ошибка",
        "answer-second-error": "6. Вторая ошибка и показ разбора",
        "training-result": "7. Итоги тренировки",
        "progress": "8–9. Прогресс, детализация и сводка по типам",
        "progress-image": "8. Визуальный экран прогресса · PNG",
        "error-replay": "10. Повтор ошибки из истории",
    }
    nav = "".join(
        f'<a href="#{html.escape(key)}">{html.escape(title)}</a>' for key, title in titles.items()
    )
    sections = []
    for key, title in titles.items():
        rows = []
        for case in ids_by_category.get(key, []):
            payload_path = f"payloads/{case['id']}.json"
            calls = "".join(api_card(call) for call in case["calls"])
            rows.append(
                f'<section class="example" id="{html.escape(case["id"])}">'
                f"<h3>{html.escape(case['label'])}</h3>"
                f'<p><a href="{html.escape(payload_path)}">JSON Bot API payload / порядок</a></p>'
                f'<div class="calls">{calls}</div></section>'
            )
        if key == "single-family":
            matrix_rows = []
            for family in families:
                if family["status"] == "public-enabled":
                    family_id = family["family_id"]
                    matrix_rows.append(
                        f"<tr><td>{html.escape(family_id)}</td><td>{html.escape(family['story'])}</td>"
                        f"<td>№{family['position']} · seed {family['seed']}</td>"
                        f'<td><a href="{html.escape(family["example"])}">payload</a></td></tr>'
                    )
            rows.insert(
                0,
                "<table><thead><tr><th>Семейство</th><th>Сюжет</th><th>Пример</th>"
                "<th>Payload</th></tr></thead><tbody>" + "".join(matrix_rows) + "</tbody></table>",
            )
        sections.append(
            f'<section id="{html.escape(key)}"><h2>{html.escape(title)}</h2>{"".join(rows)}</section>'
        )
    route_html = (
        '<section id="closed-route"><h2>11. ROUTE · закрытый пример</h2>'
        '<p class="closed">В публичной выдаче выключен; Telegram-маршрута нет. GRID-4 — '
        "синтетический кандидат, исходный растр не прошёл визуальную сверку.</p>"
        f"<p>{html.escape(route['shared_prompt'])}</p>"
        + "".join(
            f"<p><b>Задание №{i}.</b> {html.escape(condition)}</p>"
            for i, condition in enumerate(route["questions"], 1)
        )
        + "".join(
            f'<img src="{html.escape(asset["file"])}" alt="ROUTE закрытый asset">'
            for asset in route["assets"]
        )
        + '<p><a href="closed-route.json">Закрытый пример JSON</a></p></section>'
    )
    doc = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PR 113 · визуальная приёмка</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf2f5;color:#172b38;font:15px/1.5 system-ui,sans-serif}
header{padding:24px max(18px,calc((100vw - 1120px)/2));background:#16354a;color:#fff}
header p{max-width:900px;color:#d5e3ed}main{max-width:1160px;margin:auto;padding:18px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}nav a,.pill{background:#fff;color:#17506b;border-radius:999px;padding:6px 12px;text-decoration:none}
section{background:#fff;border-radius:16px;padding:18px;margin:18px 0;box-shadow:0 3px 16px #15324712}
.example{margin:14px 0;padding:14px;border:1px solid #d9e3e9;box-shadow:none}.calls{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:10px}
.payload{min-width:0;background:#f4f7f9;border:1px solid #d6e0e6;border-radius:14px;padding:10px;overflow:hidden}
.payload small{color:#536975}.bubble{margin-top:8px;background:#fff;border-radius:11px;padding:12px;overflow-wrap:anywhere;white-space:pre-wrap}
.bubble p{margin:0 0 .55rem}.bubble p:last-child{margin-bottom:0}.payload-image{display:block;max-width:100%;height:auto;margin:8px auto;border-radius:8px}
.keyboard{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.keyboard span{background:#fff;border:1px solid #cddae2;border-radius:8px;padding:4px 7px;font-size:12px}
details{margin:8px 0}pre{max-height:340px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#425966}
table{width:100%;border-collapse:collapse;margin:12px 0}td,th{border:1px solid #d5e0e7;padding:6px;text-align:left;overflow-wrap:anywhere}
.closed{border-left:4px solid #ba641f;padding:10px;background:#fff6e9}img{max-width:100%;height:auto}footer{padding:18px;color:#546b78}
@media(max-width:600px){main{padding:10px}section{padding:12px}.calls{display:block}.payload{margin:10px 0}}
</style>"""
    doc += (
        "<header><h1>PR №113 · визуальная приёмка</h1>"
        "<p>Offline HTML preview of locally captured aiogram Bot API requests. These are Chromium "
        "screenshots of the gallery, not screenshots of Telegram. Chat IDs and user data are synthetic.</p>"
        f"<p>Included: {sum(f['status'] == 'public-enabled' for f in families)} public families; "
        f"{sum(f['status'] == 'closed-disabled' for f in families)} closed ROUTE families; "
        f"{len(ids_by_category['full-scenario'])} full-question payloads across six stories.</p>"
        f'<nav>{nav}<a class="pill" href="#closed-route">11. Closed ROUTE</a></nav></header><main>'
        + "".join(sections)
        + route_html
        + "<section><h2>Матрицы и мобильные скриншоты</h2><p>"
        '<a href="family-matrix.csv">45-family matrix</a> · '
        '<a href="material-modes.csv">Material-by-mode matrix</a> · '
        '<a href="ui-route-matrix.csv">UI route acceptance matrix</a> · '
        '<a href="api-calls.json">All actual Bot API calls</a></p><p>'
        '<a href="screenshots/mobile-360.png">360 px Chromium screenshot</a> · '
        '<a href="screenshots/mobile-390.png">390 px Chromium screenshot</a> · '
        '<a href="screenshots/mobile-430.png">430 px Chromium screenshot</a></p>'
        "</section></main><footer>Generated from application presentation code with an offline "
        "aiogram BaseSession. No request was sent to Telegram.</footer></html>"
    )
    (OUT / "index.html").write_text(doc, encoding="utf-8")


def write_readme_and_route_matrix(
    cases: list[dict[str, Any]], coverage: list[dict[str, Any]]
) -> None:
    routes = [
        (
            "full",
            "Full public scenarios",
            "full-scenario",
            "tests/test_scenario_required_materials.py::test_required_payload_before_question_on_every_path",
        ),
        (
            "single",
            "Standalone public families",
            "single-family",
            "tests/test_scenario_required_materials.py::test_required_payload_before_question_on_every_path",
        ),
        (
            "personal",
            "Short personal training",
            "short-personal-garden-q3",
            "tests/test_scenario_required_materials.py::test_required_payload_before_question_on_every_path; test_short_training_data_callback_only_reads_the_current_snapshot",
        ),
        (
            "mixed",
            "Mixed and adjacent mixed training",
            "short-mixed-garden-q3",
            "tests/test_scenario_required_materials.py::test_required_payload_before_question_on_every_path; test_mixed_data_button_is_bound_to_saved_problem_without_regeneration",
        ),
        (
            "number",
            "Short training by OGE number",
            "short-number-garden-q3",
            "tests/test_scenario_required_materials.py::test_short_training_data_callback_only_reads_the_current_snapshot (number)",
        ),
        (
            "family",
            "Short training by family",
            "short-family-garden-q3",
            "tests/test_scenario_required_materials.py::test_short_training_data_callback_only_reads_the_current_snapshot (family)",
        ),
        (
            "data",
            "Saved data callback / reopen",
            "reopen-flat-q3",
            "tests/test_scenario_required_materials.py::test_short_training_data_callback_only_reads_the_current_snapshot; test_mixed_data_button_is_bound_to_saved_problem_without_regeneration",
        ),
        (
            "replay",
            "Error replay and history",
            "error-replay-tyres-q1",
            "tests/test_scenario_required_materials.py::test_required_payload_before_question_on_every_path; test_replay_data_button_preserves_original_attempt_and_snapshot",
        ),
        (
            "closed-route",
            "ROUTE closed, no Telegram route",
            "closed-route",
            "closed-route.json documents synthetic prototype mismatch",
        ),
    ]
    with (OUT / "ui-route-matrix.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("route", "coverage", "gallery_example", "evidence"))
        for route, coverage_label, example, evidence in routes:
            writer.writerow((route, coverage_label, f"index.html#{example}", evidence))

    readme = [
        "# PR #113 visual acceptance gallery",
        "",
        "Generated by `scripts/pr113_visual_gallery.py`. IDs and outcomes are synthetic.",
        "Payload examples serialize actual aiogram Bot API methods through an offline `BaseSession`.",
        "Chromium images show this local gallery, never Telegram.",
        "",
        "## Start here",
        "",
        "- [Interactive gallery](index.html)",
        "- [45-family matrix: 40 public + 5 closed ROUTE](family-matrix.csv)",
        "- [Material modes](material-modes.csv)",
        "- [Methodical family table](methodical-family-matrix.md) · [source report](../story-stabilization.md)",
        "- [Short training and callback routes](ui-route-matrix.csv)",
        "- [All serialized calls](api-calls.json)",
        "- [Closed ROUTE](closed-route.json)",
        "",
        "## Mobile screenshots",
        "",
        "- [360 px](screenshots/mobile-360.png)",
        "- [390 px](screenshots/mobile-390.png)",
        "- [430 px](screenshots/mobile-430.png)",
        "- [FLAT q3 plan at 390 px](screenshots/flat-q3-plan-390.png)",
        "",
        "## Six full scenario sets",
        "",
    ]
    for story in PUBLIC_STORIES:
        readme.append(f"- [{story}](index.html#full-{story.lower()}-q1)")
        readme.extend(
            f"  - [Question {position} payload](payloads/full-{story.lower()}-q{position}.json)"
            for position in range(1, 6)
        )
    readme.extend(["", "## All 40 standalone public families", ""])
    readme.extend(
        f"- [{row['family']}](index.html#single-{row['family'].lower()}) · "
        f"[payload](payloads/single-{row['family'].lower()}.json)"
        for row in coverage
    )
    readme.extend(["", "## UI example categories", ""])
    readme.extend(
        f"- [{case['label']}](index.html#{case['id']}) · [payload](payloads/{case['id']}.json)"
        for case in cases
        if case["category"] not in {"full-scenario", "single-family"}
    )
    readme.extend(
        [
            "",
            "Payload JSON keeps call order, reply markup, Rich HTML and PNG references. PNGs are under `assets/png/`; Rich HTML is under `payloads/rich/`.",
        ]
    )
    (OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    source = (ROOT / "reports" / "story-stabilization.md").read_text(encoding="utf-8")
    start = source.index(
        "| Семейство | Вопрос и дополнительные данные | Ответ и независимая проверка |"
    )
    end = source.index("\n\nДополнительные конструкции", start)
    table = source[start:end]
    (OUT / "methodical-family-matrix.md").write_text(
        "# Методическая матрица семейств\n\n"
        + table
        + "\n\n[Исходный отчёт](../story-stabilization.md)\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    asyncio.run(generate(args.output))


if __name__ == "__main__":
    main()
