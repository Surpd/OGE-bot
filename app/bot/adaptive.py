import asyncio
import json
import logging
import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast
from uuid import uuid4

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.adaptive.engine import CURRENT, Stage, State, family_status
from app.adaptive.planner import (
    History,
    NumberPerformance,
    PlanResult,
    SelectionReason,
    plan_with_trace,
    unlocked,
)
from app.adaptive.session import BLOCK_SIZE, OPEN_PRACTICE, Session, at_checkpoint
from app.adaptive.skills import title
from app.adaptive.sources import scenario_variant
from app.adaptive.store import overview
from app.bot.bop_copy import LABELS, reply
from app.bot.callbacks import answer_callback
from app.bot.math_layout import Role, TrainingMessage, solution_message
from app.bot.menu import main_menu, trainings_hub
from app.bot.mixed_training import _is_correct, _scenario_question, _send_problem
from app.bot.presentation import hint_message, send_text
from app.bot.scenario_materials import send_scenario_materials
from app.bot.scenario_training import public_registry
from app.bot.similar_practice import targeted_candidates
from app.bot.trainings import PART2_TRAININGS, TRAININGS
from app.config import get_settings
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    snapshot_digest,
)
from app.math.scenarios.recent_questions import NoFreshScenarioVariant, fresh_family_plan
from app.persistence.rotation_history import enabled
from app.persistence.scenario_repository import ScenarioPostgresRepository

logger = logging.getLogger(__name__)


class VariantIdentityError(ValueError):
    """A generated task has no usable mathematical identity."""


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


@lru_cache(maxsize=1)
def catalog() -> dict[str, int]:
    available = {f: t.number for t in TRAININGS if t.available for f in enabled(t.number)}
    registry = public_registry()
    for story in registry.available_stories(PracticeMode.SINGLE):
        for f in registry.adapter(story).family_registry:
            if f.available:
                available[f.family_id] = f.position
    return available


def generate(skill: str, seen: list[str]) -> dict[str, Any] | None:
    number = catalog().get(skill)
    if number is None:
        return None
    if number <= 5:
        registry = public_registry()
        story = skill.partition("-")[0]
        bundle = fresh_family_plan(
            PracticeRequest(
                PracticeMode.SINGLE, secrets.randbits(63), story, number, family_id=skill,
            ),
            registry, recent_fingerprints=seen,
        )
        if bundle.snapshot.questions[number - 1].family_id != skill:
            raise VariantIdentityError("generated a different family")
        fp = scenario_variant(bundle.snapshot, number)
        if not fp or fp in seen:
            raise VariantIdentityError("generated scenario identity does not match the selection")
        return {
            **_scenario_question(bundle.snapshot.to_snapshot(), number),
            "problem_id": str(uuid4()),
            "fingerprint": fp,
            "scenario_digest": snapshot_digest(bundle.snapshot),
            "number": number,
        }
    state: dict[str, object] = {"recent_fingerprints": seen}
    if number == 19:
        state["recent_proposition_ids"] = [p for fp in seen[-10:] for p in fp.split(":")]
    candidates = targeted_candidates(number, skill, state)
    if not candidates:
        return None
    for p in candidates:
        if p.get("fingerprint") and p.get("problem_id") != p["fingerprint"] and p.get("problem_id"):
            return p
    raise VariantIdentityError("generated task is missing its fingerprint")


def keyboard(row: Any) -> InlineKeyboardMarkup:
    pid = row["problem"] or f"{row['id']}.{row['position']}"

    def action(label: str, code: str) -> InlineKeyboardButton:
        return button(label, f"ad:{code}:{pid}")

    rows = []
    if row["outcome"] == "issued":
        rows.append([action(LABELS["hint"], "hint"), action(LABELS["solution"], "solution")])
        rows.append([action(LABELS["skip"], "skip")])
    else:
        rows.append([action(LABELS["similar"], "similar"), action(LABELS["next"], "next")])
    if row.get("snapshot") and problem_data(row).get("scenario_snapshot") is not None:
        rows.append([action(LABELS["data"], "data")])
    rows.append([action(LABELS["menu"], "menu"), action("Завершить", "finish")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def problem_data(row: Any) -> dict[str, Any]:
    saved = json.loads(row["snapshot"])
    skill = json.loads(row["plan"])[row["position"]]
    return {
        **saved,
        "number": catalog().get(skill, saved.get("number")),
        "outcome": row["outcome"],
        "hints_used": row["hints_used"],
        "prompt_message_id": row["prompt"],
    }


def _solution(problem: dict[str, Any], intro: str = "") -> TrainingMessage:
    raw = problem.get("solution", [])
    steps = [str(step) for step in raw] if isinstance(raw, list) else [str(raw)]
    return solution_message(steps, str(problem.get("correct_answer", "")), intro)


def _family_support(insights: dict[str, Any]) -> dict[str, float]:
    from app.persistence.training_insights import MIN_ANSWERED_SAMPLE

    def difficulty(row: dict[str, Any]) -> float:
        n = row.get("answered_tasks", 0)
        if n < MIN_ANSWERED_SAMPLE:
            return 0.0
        # Shrink small samples. Unknown help contributes only to answer accuracy.
        known = max(0, row.get("correct", 0) - row.get("unknown_assistance", 0))
        assisted = max(0, known - row.get("unassisted_correct", 0))
        return float((n - row.get("correct", 0) + 0.5 * assisted) / (n + MIN_ANSWERED_SAMPLE))

    return {r["family_id"]: difficulty(r) for r in insights.get("families", [])}


async def _learner_inputs(
    repository: Any, learner: int, insights: dict[str, Any] | None = None
) -> tuple[History, dict[str, Any]]:
    from app.persistence.training_insights import training_insights

    history = await overview(repository, learner)
    if insights is None:
        insights = await training_insights(repository, learner, "numbers")
    return history, insights


def _select(
    strategy: str,
    learner: int,
    history: History,
    insights: dict[str, Any],
    *,
    prefix: list[str] | None = None,
    excluded: list[str] | None = None,
    number: int | None = None,
    seed: str | None = None,
    as_of: datetime | None = None,
    size: int = 5,
    recommendations_only: bool = False,
    difficulties: dict[str, int] | None = None,
    include_practice: bool = True,
) -> PlanResult:
    choices = catalog()
    if number is not None:
        choices = {f: n for f, n in choices.items() if n == number}
    if strategy == "mixed":
        return plan_with_trace([], choices, prefix=prefix or (), excluded=excluded or (), size=size,
                    seed=seed or "0")
    performance = {
        int(number): NumberPerformance(int(row["answered_tasks"]), int(row["correct"]))
        for number, row in insights.get("numbers", {}).items()
    }
    return plan_with_trace(
        history, choices, prefix=prefix or (), excluded=excluded or (), size=size,
        number_performance=performance, support=_family_support(insights),
        seed=seed or str(learner), as_of=as_of or datetime.now(UTC),
        recommendations_only=recommendations_only, difficulties=difficulties,
        include_practice=include_practice,
    )


def _recommendation_action(item: SelectionReason) -> tuple[str, str]:
    if item.by_number:
        return f"Тренировать №{item.number}", f"train:number:{item.number}"
    return title(item.family), f"train:family:{item.family}"


def _recommendation_text(item: SelectionReason) -> str:
    if item.by_number:
        return f"{item.reason.capitalize()}. Стоит потренироваться."
    return f"{title(item.family)} · {item.reason}."


async def progress_target(repository: Any, learner: int, insights: dict[str, Any]) -> None:
    if not await repository.personal_enabled(learner):
        return
    history, insights = await _learner_inputs(repository, learner, insights)
    store = Session(repository, learner)
    current = await store.current()
    if current and current["strategy"] == "personal" and current["problem"]:
        insights["personal_tip"] = "Можно продолжить сохранённую персональную тренировку."
        insights["personal_action"] = ("Продолжить", "train:resume")
        return
    recommendations = _select(
        "personal", learner, history, insights,
        excluded=await store.excluded_for_learner(), size=1, recommendations_only=True,
    ).reasons
    if recommendations:
        item = recommendations[0]
        insights["personal_tip"] = _recommendation_text(item)
        insights["personal_action"] = _recommendation_action(item)
    else:
        insights["personal_tip"] = "Выбери персональную тренировку, чтобы попробовать новые задачи."
        insights["personal_action"] = ("Персональная тренировка", "train:personal")


async def _pending_task(
    message: Message, repository: Any, store: Session, row: Any, *, exhausted: bool,
) -> None:
    token = f"{row['id']}.{row['position']}"
    rows = []
    if exhausted:
        rows.append([button("🔁 Повторить вариант", f"ad:repeat:{token}")])
    else:
        rows.append([button("Попробовать ещё раз", f"ad:retry:{token}")])
    scope = json.loads(row["scope"])
    if scope.get("similar_position") == row["position"]:
        rows.append([button("Вернуться к заданию", f"ad:back:{token}")])
    rows.append([button("Выбрать другой тип", "train:areas")])
    rows.append([
        button(LABELS["menu"], f"ad:menu:{token}"), button("Завершить", f"ad:finish:{token}"),
    ])
    sent = await send_text(
        message, repository,
        "Ты уже видел все варианты этого типа. Можно повторить один из них."
        if exhausted else "Не получилось подготовить задачу. Попробуй ещё раз.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), user_id_override=store.learner,
    )
    await store.set_pending_prompt(row, sent.message_id)


async def present(
    message: Message, repository: Any, learner: int, *, repeat: bool = False,
    expected_prompt: int | None = None,
) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row is None:
        return
    if expected_prompt is not None and (row["problem"] or row["prompt"] != expected_prompt):
        return
    if at_checkpoint(row):
        await checkpoint(message, repository, store, row)
        return
    skills = json.loads(row["plan"])
    strategy = str(row.get("strategy", "personal"))
    if not row["problem"]:
        row = await _issue_task(message, repository, store, row, skills, repeat=repeat)
    elif strategy == "personal":
        history, insights = await _learner_inputs(repository, learner)
        scope = json.loads(row["scope"])
        updated = list(_select(
            strategy, learner, history, insights, prefix=skills[:row["position"] + 1],
            excluded=await store.excluded_for_learner(), size=len(skills),
            seed=str(scope.get("plan_seed", learner)),
        ).slots)
        if len(updated) == len(skills) and updated != skills:
            if not await store.refresh(row, updated):
                return
    if not row:
        return
    data = problem_data(row)
    mode_name = {
        "personal": "Персональная тренировка",
        "mixed": "Смешанная тренировка",
        "number": "Тренировка по номеру",
        "family": title(json.loads(row["plan"])[row["position"]]),
    }.get(strategy, "Тренировка")
    position = f"№{data['number']} — задание {row['position'] + 1}"
    if strategy not in OPEN_PRACTICE:
        position += f" из {len(skills)}"
    await _send_problem(
        message,
        repository,
        store,
        data,
        user_id=learner,
        keyboard=keyboard(row),
        heading=mode_name,
        position_text=position,
    )


async def _issue_task(
    message: Message, repository: Any, store: Session, row: Any, skills: list[str],
    *, repeat: bool,
) -> Any:
    position, strategy = row["position"], row["strategy"]
    scope = json.loads(row["scope"])
    exact = strategy == "family" or scope.get("similar_position") == position
    excluded = [] if exact or repeat else await store.excluded_for_learner()
    history, insights = (
        await _learner_inputs(repository, store.learner)
        if not exact and not repeat and strategy in {"personal", "number"} else ([], {})
    )
    exhausted_plan = None
    technical_failure = bool(excluded)
    for _ in range(8):  # Try different eligible families, never random families within one search.
        updated = skills
        if not exact and not repeat and (strategy == "personal" or skills[position] in excluded):
            updated = list(_select(
                strategy, store.learner, history, insights, prefix=skills[:position],
                excluded=excluded, number=scope.get("number"), size=len(skills),
                seed=str(scope.get("plan_seed", store.learner)),
            ).slots)
        if len(updated) <= position:
            break
        if updated != skills and not await store.refresh(row, updated):
            return None
        skills = updated
        skill = skills[position]
        seen = await store.seen(row["owner"], skill)
        try:
            candidate = await asyncio.to_thread(generate, skill, seen)
        except NoFreshScenarioVariant:
            exhausted_plan = skills
            try:
                candidate = await asyncio.to_thread(generate, skill, []) if repeat else None
            except (ValueError, RuntimeError, KeyError, OSError):
                logger.warning("Could not reissue a scenario for family %s", skill)
                technical_failure = True
                candidate = None
        except (ValueError, RuntimeError, KeyError, OSError) as error:
            logger.warning("Adaptive generation failed for %s (%s)", skill, type(error).__name__)
            technical_failure = True
            candidate = None
        else:
            if repeat:  # Repeat is available only after checking the entire certified pool.
                candidate = None
            technical_failure |= candidate is None
        if candidate:
            if not await store.save(row, skill, candidate, repeat=repeat):
                # A competing update can reserve the cursor or issue this very variant.
                # Neither case proves that the family is exhausted.
                current = await store.current()
                if not _same_pending(current, row, skills):
                    return None
                technical_failure = True
                continue
            current = await store.current()
            if current and str(current["problem"]) == candidate["problem_id"]:
                return current
            return None
        if exact or repeat:
            break
        excluded.append(skill)
    else:
        technical_failure = True
    current = await store.current()
    if _same_pending(current, row, skills) and (
        await repository.user_state(store.learner) == "adaptive"
    ):
        exhausted = exhausted_plan is not None and not technical_failure
        if exhausted and exhausted_plan != skills:
            assert exhausted_plan is not None
            if not await store.refresh(row, exhausted_plan):
                return None
        await _pending_task(message, repository, store, current, exhausted=exhausted)
    return None


def _same_pending(current: Any, row: Any, plan: list[str]) -> bool:
    return (
        current is not None and current["problem"] is None
        and json.loads(current["plan"]) == plan
        and all(current[key] == row[key] for key in ("id", "position", "revision", "prompt"))
    )


def _mode_plan(
    strategy: str,
    learner: int,
    history: History,
    insights: dict[str, Any],
    *,
    number: int | None = None,
    family: str | None = None,
    excluded: list[str] | None = None,
    seed: str | None = None,
) -> list[str]:
    if strategy == "family":
        return [family] * 5 if family is not None and family in catalog() else []
    return list(_select(
        strategy, learner, history, insights, number=number, excluded=excluded, seed=seed,
    ).slots)


def _requested_mode(row: Any, strategy: str, number: int | None, family: str | None) -> bool:
    if str(row["strategy"]) != strategy:
        return False
    scope = row["scope"] or {}
    if isinstance(scope, str):
        scope = json.loads(scope)
    return (strategy != "number" or scope.get("number") == number) and (
        strategy != "family" or scope.get("family") == family
    )


def _switch_callback(strategy: str, number: int | None, family: str | None) -> str:
    codes = {"personal": "p", "mixed": "m", "number": "n", "family": "f"}
    value = family if strategy == "family" else str(number) if strategy == "number" else ""
    return f"train:x:{codes[strategy]}" + (f":{value}" if value else "")


async def start(
    message: Message,
    repository: Any,
    *,
    strategy: str = "personal",
    number: int | None = None,
    family: str | None = None,
) -> None:
    if not get_settings().oge_adaptive_enabled or not message.from_user:
        return
    learner = message.from_user.id
    if strategy == "personal" and not await repository.personal_enabled(learner):
        await send_text(
            message,
            repository,
            "Персональная тренировка выключена в настройках.",
            reply_markup=main_menu(),
            user_id_override=learner,
        )
        return
    pool = getattr(repository, "_pool", None)
    store = Session(repository, learner) if pool is not None else None
    current = await store.current() if store else None
    if current is not None and not _requested_mode(current, strategy, number, family):
        personal_available = await repository.personal_enabled(learner)
        current_name = {
            "personal": "персональная",
            "mixed": "смешанная",
            "number": "по номеру",
            "family": "по типу",
        }.get(str(current["strategy"]), "короткая")
        rows = [
            [button("Завершить и переключиться", _switch_callback(
                strategy, number, family,
            ))],
            [button("↩ К тренировкам", "train:hub")],
        ]
        if current["strategy"] != "personal" or personal_available:
            rows.insert(0, [button(f"Продолжить: {current_name}", "train:resume")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        await repository.save_user_state(learner, "trainings")
        await send_text(
            message, repository,
            "У тебя уже есть начатая тренировка. Продолжить её или выбрать другую?",
            reply_markup=markup, user_id_override=learner,
        )
        return
    if current is None:
        if store is None:
            return
        history, insights = (
            await _learner_inputs(repository, learner)
            if strategy in {"personal", "number"}
            else ([], {})
        )
        plan_seed = str(learner) if strategy == "personal" else secrets.token_hex(8)
        skills = _mode_plan(
            strategy, learner, history, insights, number=number, family=family,
            excluded=await store.excluded_for_learner(), seed=plan_seed,
        )
        if not skills:
            await send_text(
                message,
                repository,
                "Сейчас нет свежих задач для этой тренировки.",
                reply_markup=main_menu(),
                user_id_override=learner,
            )
            return
        scope: dict[str, Any] = {"number": number} if strategy == "number" else (
            {"family": family} if strategy == "family" else {}
        )
        scope["plan_seed"] = plan_seed
        await store.start(skills, strategy=strategy, scope=scope)
    elif store:
        await store.start([])
    await present(message, repository, learner)


async def trainings(
    message: Message, repository: Any, oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    from app.bot.router import _has_resumable_session

    if not message.from_user:
        return
    learner = message.from_user.id
    short_enabled = get_settings().oge_adaptive_enabled
    personal_available = short_enabled and await repository.personal_enabled(learner)
    has_session = await _has_resumable_session(repository, learner, oge15_repository)
    await repository.save_user_state(learner, "trainings")
    await send_text(
        message, repository, TrainingMessage(("title", "Тренировки")),
        reply_markup=trainings_hub(
            personal_enabled=personal_available, short_enabled=short_enabled,
            has_session=has_session,
        ),
        user_id_override=learner,
    )


def area_keyboard() -> InlineKeyboardMarkup:
    numbers = sorted(set(catalog().values()))
    rows = [[button("№1–5 · Связанный сюжет", "nav:linked")]]
    rows.extend([button(f"№{n}", f"train:area:{n}") for n in numbers[i:i + 5]]
                for i in range(0, len(numbers), 5))
    if get_settings().oge_part2_enabled:
        written = [button(f"№{t.number}", f"p2:menu:{t.number}") for t in PART2_TRAININGS]
        rows.extend(written[i:i + 3] for i in range(0, len(written), 3))
    rows.append([button("↩ К тренировкам", "nav:trainings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def family_area_keyboard(number: int, page: int = 0) -> InlineKeyboardMarkup:
    families = sorted((skill for skill, n in catalog().items() if n == number), key=title)
    page_count = max(1, (len(families) + 4) // 5)
    page = min(max(0, page), page_count - 1)
    rows = [[button(f"Весь №{number}", f"train:number:{number}")]]
    rows.extend([[button(title(skill), f"train:family:{skill}")]
                 for skill in families[page * 5:(page + 1) * 5]])
    arrows = []
    if page:
        arrows.append(button("←", f"train:area:{number}:{page - 1}"))
    if page + 1 < page_count:
        arrows.append(button("→", f"train:area:{number}:{page + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([button("↩ К номерам", "train:areas")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_REASON_NAMES = {
    "calculation": "вычислительная ошибка",
    "lost_root": "потерян корень",
    "equivalence": "нарушена равносильность",
    "domain": "не учтена область допустимых значений",
    "justification": "ошибка в обосновании",
    "theorem": "неверно применена теорема",
    "incomplete_proof": "неполное доказательство",
    "graph": "ошибка построения графика",
    "model": "ошибка в математической модели",
}


def stage_line(s: State) -> str:
    return family_status(s).label


def summary(history: History, offset: int = 0) -> str:
    if not history:
        return "Здесь появятся результаты по типам задач."
    first = [s for n, _, s, _ in history if n <= 19]
    lines = [
        "Сводка по типам задач",
        f"Открыто пробелов · {sum(s.opened > s.closed for s in first)}",
        f"На закреплении · {sum(s.stage == Stage.PRACTICE for s in first)}",
        f"Закрыто пробелов сейчас · {sum(s.closed > 0 and s.opened == s.closed for s in first)}",
    ]
    for number, skill, s, _ in history[offset : offset + 1]:
        lines.extend(["", f"№{number} · {title(skill)}"])
        if number >= 20:
            if s.stage == Stage.CHECK:
                lines.append("Можно потренироваться на новой письменной работе этого подтипа.")
            continue
        lines.append(stage_line(s))
        if s.opened > s.closed or s.practice:
            lines.append(
                f"Новые варианты подряд без помощи · {s.practice}/{CURRENT.practice_count}"
            )
    return "\n".join(lines)


async def gaps(message: Message, repository: Any, offset: int = 0) -> None:
    if not get_settings().oge_adaptive_enabled or not message.from_user:
        return
    learner = message.from_user.id
    from app.bot.progress import _FAMILY_PRIORITY

    projected, insights = await _learner_inputs(repository, learner)
    answered = {row["family_id"]: row["answered_tasks"] for row in insights.get("families", [])}
    history = sorted(
        (row for row in projected if row[2].stage != Stage.UNCHECKED),
        key=lambda h: (
            h[0] >= 20,
            _FAMILY_PRIORITY.get(h[2].stage, 4),
            -answered.get(h[1], 0),
            h[0],
            h[1],
        ),
    )
    rows = []
    for number, skill, state, _ in history[offset : offset + 1]:
        if (
            number >= 20
            and state.stage not in {Stage.UNCHECKED, Stage.CONFIRMED}
            and get_settings().oge_part2_enabled
        ):
            rows.append([button(f"Письменная работа №{number}", f"p2:open:{number}:{skill}")])
    if unlocked(projected) and await repository.personal_enabled(learner):
        rows.append([button("Персональная тренировка", "nav:adaptive")])
    body = summary(history, offset)
    if history[offset : offset + 1]:
        from app.bot.progress import encode_record_ref

        number, skill, state, _ = history[offset]
        log = await repository._pool.fetch(
            """SELECT source,task,outcome,attempt,reason,occurred,confirmed_error_reasons
            FROM adaptive_learning_events e JOIN users u ON u.id=e.owner
            WHERE u.telegram_user_id=$1 AND e.skill=$2 AND e.reason IS NOT NULL
            ORDER BY occurred DESC,ordinal DESC LIMIT 4""",
            learner,
            skill,
        )
        previous = await repository._pool.fetchval(
            """SELECT max(m.occurred) FROM adaptive_past_milestones m JOIN users u ON u.id=m.owner
            WHERE u.telegram_user_id=$1 AND m.skill=$2 AND m.reason='gap_closed'""",
            learner,
            skill,
        )
        if previous:
            body += f"\nПробел закрывался по прежним правилам · {previous:%d.%m.%Y}"
        if log:
            body += "\n\nПоследние свидетельства"
        refs = []
        for r in log:
            what = {
                "correct": "верный ответ",
                "wrong": "ошибка",
                "solution": "просмотр разбора",
            }.get(r["outcome"], "проверка")
            detail = {
                "gap_opened": "пробел обнаружен",
                "gap_reopened": "пробел открыт снова",
                "independent_success": "самостоятельное решение",
                "written_recommended": "рекомендация по подтипу",
                "gap_closed": "пробел закрыт",
                "skill_confirmed": "три самостоятельных решения подряд",
                "thematic_check_needed": "нужна проверка на одной теме",
                "independent_check_needed": "нужен новый вариант без помощи",
            }.get(r["reason"], "")
            body += f"\n{r['occurred']:%d.%m} · {what}"
            if r["attempt"]:
                body += f", попытка {r['attempt']}"
            if detail:
                body += f" · {detail}"
            if r["confirmed_error_reasons"]:
                labels = [_REASON_NAMES[code] for code in r["confirmed_error_reasons"]]
                body += "\nПреподаватель отметил: " + ", ".join(labels)
            source = {"ordinary": "o", "personal": "o", "mixed": "m", "scenario": "s"}.get(
                r["source"]
            )
            if source:
                token = encode_record_ref(f"{source}:{r['task']}")
                if token not in refs:
                    refs.append(token)
        if refs:
            rows.append(
                [
                    button(f"Задача {i}", f"progress:item:{token}:h0")
                    for i, token in enumerate(refs, 1)
                ]
            )
        if number >= 20:
            remaining = await repository._pool.fetchval(
                """SELECT count(DISTINCT v.task_id)
                FROM part2_versions v JOIN part2_cards c USING(task_id)
                WHERE c.subtype_id=$1 AND v.available AND v.reviewed AND NOT EXISTS(
                SELECT FROM part2_issues i WHERE i.task_id=v.task_id AND i.owner=$2)""",
                skill,
                learner,
            )
            body += f"\nНовых проверенных карточек подтипа · {remaining}"
    arrows = []
    if offset:
        arrows.append(button("Назад", f"nav:gaps:{max(0, offset - 1)}"))
    if offset + 1 < len(history):
        arrows.append(button("Дальше", f"nav:gaps:{offset + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([button("Мой прогресс", "nav:progress"), button("В меню", "nav:main")])
    await repository.save_user_state(learner, "progress")
    await send_text(
        message,
        repository,
        body,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        user_id_override=learner,
    )


async def answer(message: Message, repository: Any) -> None:
    if not get_settings().oge_adaptive_enabled or not message.from_user or not message.text:
        raise SkipHandler
    learner = message.from_user.id
    if await repository.user_state(learner) != "adaptive":
        raise SkipHandler
    store = Session(repository, learner)
    row = await store.current()
    if (
        not row or row["outcome"] != "issued" or not row["problem"] or not row["prompt"]
        or message.message_id <= row["prompt"]
    ):
        return
    reply_to = message.reply_to_message
    if reply_to and reply_to.message_id != row["prompt"]:
        return
    problem = problem_data(row)
    correct = await asyncio.to_thread(_is_correct, problem["number"], problem, message.text)
    if correct is None:
        await send_text(message, repository, "Проверь формат ответа и попробуй ещё раз.")
        return
    result = await store.act(
        row["problem"],
        row["prompt"],
        "answer",
        raw=message.text,
        correct=correct,
        message_id=message.message_id,
        revision=row["revision"],
    )
    if result == "stale":
        return
    terminal_result = result.removeprefix("completed_")
    text = {
        "solved": reply("corrected" if row.get("attempt_count") else "correct", message.message_id),
        "issued": reply("wrong", message.message_id),
        "failed": _solution(problem, reply("review", message.message_id)),
    }[terminal_result]
    if terminal_result == "solved" and not result.startswith("completed_"):
        delta = await store.answer_delta(row["id"], message.message_id)
        if delta is not None:
            if delta["reason"] == "independent_review":
                text += " " + reply("series", message.message_id)
            else:
                state = json.loads(delta["after_state"])
                if delta.get("selection") == "similar":
                    text = reply("analog", message.message_id)
                text += f" Серия этого типа: {state['practice']}/{CURRENT.practice_count}."
    if result.startswith("completed_"):
        if terminal_result == "failed":
            await send_text(
                message, repository, text, user_id_override=learner, math_family=problem,
            )
        await completion(message, repository, store, row, reply("done", message.message_id))
        return
    await feedback(message, repository, learner, text)


async def feedback(message: Message, repository: Any, learner: int, text: str) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row and row["problem"]:
        if at_checkpoint(row):
            if isinstance(text, TrainingMessage):
                await send_text(
                    message, repository, text,
                    user_id_override=learner, math_family=problem_data(row),
                )
            await checkpoint(message, repository, store, row)
            return
        sent = await send_text(
            message,
            repository,
            text,
            reply_markup=keyboard(row),
            user_id_override=learner,
            math_family=(
                problem_data(row)
                if isinstance(text, TrainingMessage) and text.has_role("hint", "solution")
                else None
            ),
        )
        await store.set_prompt(learner, str(row["problem"]), sent.message_id)


def _summary_changes(deltas: list[Any]) -> list[str]:
    # Combine contiguous series changes only when the projection really connects them.
    streaks: dict[str, list[tuple[int, int]]] = {}
    reviews: set[str] = set()
    gap_changes: dict[str, str] = {}
    for delta in deltas:
        family = delta["skill"]
        if delta["reason"] == "independent_review":
            reviews.add(family)
            continue
        if delta["reason"] in {"gap_opened", "gap_reopened", "gap_closed"}:
            gap_changes[family] = (
                "серия восстановлена" if delta["reason"] == "gap_closed"
                else "этот тип стоит потренировать"
            )
        before = json.loads(delta["before_state"]) if delta["before_state"] else {"practice": 0}
        after = json.loads(delta["after_state"])
        if before["practice"] != after["practice"]:
            segments = streaks.setdefault(family, [])
            if segments and segments[-1][1] == before["practice"]:
                segments[-1] = (segments[-1][0], after["practice"])
            else:
                segments.append((before["practice"], after["practice"]))
    changes = []
    for family, segments in streaks.items():
        series = ", ".join(
            f"{before}/{CURRENT.practice_count} → {after}/{CURRENT.practice_count}"
            for before, after in segments if before != after
        )
        if series:
            changes.append(f"• {title(family)} · серия {series}.")
    changes.extend(f"• {title(family)} · {detail}." for family, detail in gap_changes.items()
                   if family not in streaks)
    changes.extend(f"• {title(family)} · снова получилось после перерыва."
                   for family in sorted(reviews))
    return changes


def _result_lines(totals: Any) -> str:
    return "\n".join((
        f"Решено верно: {totals['solved']} из {totals['issued']}",
        f"Самостоятельно: {totals['independent']} из {totals['issued']}",
        f"Пропущено: {totals.get('skipped', 0)}",
    ))


async def checkpoint(message: Message, repository: Any, store: Session, row: Any) -> None:
    completed = row["position"] + 1
    start_position = completed - BLOCK_SIZE
    deltas = await store.summary_deltas(row["id"], from_position=start_position)
    totals = await store.totals(row["id"], from_position=start_position)
    blocks: list[tuple[Role, str]] = [
        ("title", "Промежуточный итог"),
        ("position", f"Задания {start_position + 1}–{completed}"),
        ("stats", _result_lines(totals)),
    ]
    changes = _summary_changes(deltas)
    if changes:
        blocks.extend((("section", "Твой прогресс"), ("stats", "\n".join(changes))))
    pid = row["problem"]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [button("➡ Продолжить", f"ad:continue:{pid}"), button("Завершить", f"ad:finish:{pid}")],
        [button(LABELS["menu"], f"ad:menu:{pid}")],
    ])
    sent = await send_text(
        message, repository, TrainingMessage(*blocks), reply_markup=markup,
        user_id_override=store.learner,
    )
    await store.set_prompt(store.learner, str(pid), sent.message_id)


async def completion(
    message: Message, repository: Any, store: Session, row: Any, heading: str
) -> None:
    deltas = await store.summary_deltas(row["id"])
    totals = await store.totals(row["id"])
    if not totals["issued"]:
        await trainings(message, repository)
        return
    blocks: list[tuple[Role, str]] = [("title", heading), ("stats", _result_lines(totals))]
    changes = _summary_changes(deltas)
    if changes:
        blocks.extend((("section", "Твой прогресс"), ("stats", "\n".join(changes))))
    personal_available = await repository.personal_enabled(store.learner)
    recommendations: tuple[SelectionReason, ...] = ()
    if personal_available:
        history, insights = await _learner_inputs(repository, store.learner)
        recommendations = _select(
            "personal", store.learner, history, insights,
            excluded=await store.excluded_for_learner(), size=1, recommendations_only=True,
            difficulties=await store.difficulties(row["id"]),
            include_practice=totals["independent"] < totals["issued"],
        ).reasons
    rows = []
    if recommendations:
        item = recommendations[0]
        detail = _recommendation_text(item)
        if not item.by_number:
            detail = f"№{item.number} · {detail}"
        blocks.extend((("section", "Что потренировать дальше"), ("recommendation", detail)))
        rows.append([button(*_recommendation_action(item))])
    if personal_available:
        rows.append([button("Персональная тренировка", "train:personal")])
    else:
        rows.append([button("К тренировкам", "train:hub")])
    rows.append([button(LABELS["progress"], "train:progress"), button(LABELS["menu"], "nav:main")])
    text = TrainingMessage(*blocks)
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await repository.save_user_state(store.learner, "trainings")
    await send_text(
        message, repository, text, reply_markup=keyboard, user_id_override=store.learner
    )


async def callback(cb: CallbackQuery, repository: Any) -> None:
    if not get_settings().oge_adaptive_enabled or not isinstance(cb.message, Message):
        await answer_callback(cb)
        return
    learner = cb.from_user.id
    raw, _, nav_revision = (cb.data or "").partition("~")
    if raw.startswith("train:"):
        from app.bot.navigation import NavigationMessage

        if not nav_revision or not await repository.claim_navigation_message(
            learner, cb.message.message_id, nav_revision
        ):
            await answer_callback(cb, "Это меню устарело. Открой тренировки снова.")
            return
        parts = raw.split(":")
        action = parts[1] if len(parts) > 1 else ""
        view = NavigationMessage(cb.message, cb, repository, edit_navigation=False)
        actor_message = cast(Message, view)
        if action == "hub":
            await trainings(actor_message, repository)
        elif action == "progress" and len(parts) == 2:
            from app.bot.router import show_progress

            await show_progress(actor_message, repository)
        elif action == "areas" and (len(parts) == 2 or parts[2].isdigit()):
            await repository.save_user_state(learner, "trainings")
            await send_text(actor_message, repository, TrainingMessage(("title", "Выбери номер")),
                            reply_markup=area_keyboard(), user_id_override=learner)
        elif action == "area" and len(parts) in {3, 4} and parts[2].isdigit():
            number = int(parts[2])
            page = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else 0
            if number not in catalog().values():
                await answer_callback(cb, "Этот номер пока недоступен.")
                return
            await send_text(actor_message, repository, f"№{number}: весь номер или конкретный тип?",
                            reply_markup=family_area_keyboard(number, page),
                            user_id_override=learner)
        elif action in {"personal", "mixed"} and len(parts) == 2:
            await start(actor_message, repository, strategy=action)
        elif action == "resume" and len(parts) == 2:
            store = Session(repository, learner)
            current = await store.current()
            if current is None:
                await answer_callback(cb, "Сохранённая тренировка уже завершена.")
                return
            if current["strategy"] == "personal" and not await repository.personal_enabled(
                learner
            ):
                await answer_callback(
                    cb, "Персональная тренировка выключена. Выбери другой режим."
                )
                return
            await store.start([])
            await present(actor_message, repository, learner)
        elif action == "number" and len(parts) == 3 and parts[2].isdigit():
            await start(actor_message, repository, strategy="number", number=int(parts[2]))
        elif action == "family" and len(parts) == 3:
            await start(actor_message, repository, strategy="family", family=parts[2])
        elif action == "x" and len(parts) in {3, 4}:
            requested_strategy = {
                "p": "personal", "m": "mixed", "n": "number", "f": "family",
            }.get(
                parts[2], ""
            )
            requested_number = int(parts[3]) if (
                requested_strategy == "number" and len(parts) == 4 and parts[3].isdigit()
            ) else None
            requested_family = (
                parts[3] if requested_strategy == "family" and len(parts) == 4 else None
            )
            if requested_strategy not in {"personal", "mixed", "number", "family"} or (
                requested_strategy == "number" and requested_number is None
            ) or (requested_strategy == "family" and requested_family is None):
                await answer_callback(cb, "Это направление недоступно.")
                return
            store = Session(repository, learner)
            current = await store.current()
            if current is not None:
                disabled_personal = (
                    current["strategy"] == "personal"
                    and not await repository.personal_enabled(learner)
                )
                if disabled_personal:
                    result = await store.finish_disabled_personal(
                        current["id"], current["position"], current["problem"],
                        revision=current["revision"],
                    )
                else:
                    await store.start([])
                    result = await store.act(
                        current["problem"], current["prompt"], "finish",
                        session_id=current["id"], position=current["position"],
                        revision=current["revision"],
                    )
                if result != "finished":
                    await answer_callback(cb, "Тренировка уже изменилась.")
                    return
                await completion(
                    actor_message, repository, store, current,
                    "Тренировка завершена досрочно.",
                )
            await start(
                actor_message, repository, strategy=requested_strategy,
                number=requested_number, family=requested_family,
            )
        else:
            await answer_callback(cb, "Это направление недоступно.")
            return
        await answer_callback(cb)
        return
    store = Session(repository, learner)
    row = await store.current()
    parts = raw.split(":")
    if (
        not row
        or len(parts) != 3
        or str(row["problem"] or f"{row['id']}.{row['position']}") != parts[2]
        or await repository.user_state(learner) != "adaptive"
        or row["prompt"] != cb.message.message_id
    ):
        await answer_callback(cb, "Это задание уже сменилось.")
        return
    action = parts[1]
    if action == "data":
        data = problem_data(row)
        raw_scenario = data.get("scenario_snapshot")
        await answer_callback(cb)
        if isinstance(raw_scenario, dict):
            snapshot = await asyncio.to_thread(ScenarioSnapshot.from_snapshot, raw_scenario)
            await send_scenario_materials(
                cb.message, repository, snapshot, data["number"], user_id=learner, full_story=True,
            )
        return
    if action in {"retry", "repeat"} and row["problem"] is None:
        await present(
            cb.message, repository, learner, repeat=action == "repeat",
            expected_prompt=cb.message.message_id,
        )
    elif action == "back" and row["problem"] is None:
        result = await store.cancel_similar(
            row["id"], row["position"], revision=row["revision"], prompt=cb.message.message_id,
        )
        if result == "exhausted":
            await present(cb.message, repository, learner)
    elif action == "continue" and at_checkpoint(row):
        scope = json.loads(row["scope"])
        strategy = row["strategy"]
        history, insights = (
            await _learner_inputs(repository, learner) if strategy == "number" else ([], {})
        )
        next_block = _mode_plan(
            strategy, learner, history, insights, number=scope.get("number"),
            family=scope.get("family"), seed=secrets.token_hex(8),
        )
        result = await store.act(
            row["problem"], row["prompt"], action, session_id=row["id"],
            position=row["position"], revision=row["revision"], next_block=next_block,
        )
        if result == "next":
            await present(cb.message, repository, learner)
        elif not next_block:
            await answer_callback(
                cb, "Сейчас это направление недоступно. Можно завершить тренировку.",
            )
            return
    elif action == "menu":
        result = await store.act(
            row["problem"], row["prompt"], "menu", session_id=row["id"],
            position=row["position"], revision=row["revision"],
        )
        if result != "paused":
            await answer_callback(cb, "Это задание уже сменилось.")
            return
        await send_text(
            cb.message,
            repository,
            "Тренировка сохранена.",
            reply_markup=main_menu(has_session=True),
            user_id_override=learner,
        )
    elif action == "similar":
        result = await store.choose_similar(
            row["id"], row["position"], row["problem"], revision=row["revision"],
            prompt=cb.message.message_id,
        )
        if result == "next":
            await present(cb.message, repository, learner)
        elif result == "full":
            if at_checkpoint(row):
                await checkpoint(cb.message, repository, store, row)
        else:
            await answer_callback(cb, "Похожее задание сейчас недоступно.")
            return
    else:
        result = await store.act(
            row["problem"], row["prompt"], action, session_id=row["id"],
            position=row["position"], revision=row["revision"],
        )
        if result in {"completed_skip", "completed_solution"}:
            problem = problem_data(row)
            terminal_text = (
                _solution(problem)
                if result == "completed_solution" else "Задание пропущено."
            )
            await send_text(
                cb.message, repository, terminal_text, user_id_override=learner,
                math_family=problem if result == "completed_solution" else None,
            )
            await completion(
                cb.message, repository, store, row, "Тренировка завершена!",
            )
            await answer_callback(cb)
            return
        if result in {"finished", "completed"}:
            await completion(cb.message, repository, store, row, "Тренировка завершена.")
        elif result == "next":
            await present(cb.message, repository, learner)
        elif result in {"hint", "skip", "solution", "no_hint"}:
            p = problem_data(row)
            text = {
                "skip": "Задание пропущено.",
                "solution": _solution(p),
                "no_hint": "Подсказок больше нет.",
            }.get(result)
            await feedback(
                cb.message,
                repository,
                learner,
                text or hint_message(p["hints"][row["hints_used"]], p),
            )
    await answer_callback(cb)
