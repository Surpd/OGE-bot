import asyncio
import json
import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast
from uuid import uuid4

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.adaptive.engine import CURRENT, Stage, State, family_status
from app.adaptive.planner import History, NumberPerformance, plan, unlocked
from app.adaptive.session import Session
from app.adaptive.skills import title
from app.adaptive.sources import scenario_variant
from app.adaptive.store import overview
from app.bot.callbacks import answer_callback
from app.bot.menu import main_menu, trainings_hub
from app.bot.mixed_training import _is_correct, _scenario_question, _send_problem
from app.bot.presentation import hint_message, send_text
from app.bot.scenario_training import public_registry
from app.bot.similar_practice import targeted_candidates
from app.bot.trainings import TRAININGS
from app.config import get_settings
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    snapshot_digest,
)
from app.persistence.rotation_history import enabled


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
        for _ in range(12):
            bundle = build_practice_plan(
                PracticeRequest(PracticeMode.SINGLE, secrets.randbits(63), story, number), registry
            )
            q = bundle.snapshot.questions[number - 1]
            fp = scenario_variant(bundle.snapshot, number)
            if q.family_id == skill and fp not in seen:
                return {
                    **_scenario_question(bundle.snapshot.to_snapshot(), number),
                    "problem_id": str(uuid4()),
                    "fingerprint": fp,
                    "scenario_digest": snapshot_digest(bundle.snapshot),
                    "number": number,
                }
        return None
    state: dict[str, object] = {"recent_fingerprints": seen}
    if number == 19:
        state["recent_proposition_ids"] = [p for fp in seen[-10:] for p in fp.split(":")]
    candidates = targeted_candidates(number, skill, state)
    return next(
        (
            p
            for p in candidates
            if p.get("fingerprint")
            and p.get("problem_id")
            and p.get("fingerprint") != p.get("problem_id")
        ),
        None,
    )


def keyboard(row: Any) -> InlineKeyboardMarkup:
    pid = row["problem"] or f"{row['id']}.{row['position']}"

    def action(label: str, code: str) -> InlineKeyboardButton:
        return button(label, f"ad:{code}:{pid}")

    rows = []
    if row["outcome"] == "issued":
        rows.append([action("Подсказка", "hint"), action("Разбор", "solution")])
        rows.append([action("Пропустить", "skip")])
    else:
        rows.append([action("Похожее", "similar"), action("Дальше", "next")])
    rows.append([action("В меню", "menu"), action("Завершить", "finish")])
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


def _solution_text(problem: dict[str, Any]) -> str:
    raw = problem.get("solution", [])
    if isinstance(raw, list):
        return "\n".join(str(step) for step in raw)
    return str(raw)


def progress_weights(insights: dict[str, Any]) -> dict[str, float]:
    from app.persistence.training_insights import MIN_ANSWERED_SAMPLE

    def difficulty(row: dict[str, Any]) -> float:
        n = row.get("answered_tasks", 0)
        if n < MIN_ANSWERED_SAMPLE:
            return 0.0
        # Shrink small samples. Unknown help contributes only to answer accuracy.
        known = max(0, row.get("correct", 0) - row.get("unknown_assistance", 0))
        assisted = max(0, known - row.get("unassisted_correct", 0))
        return float((n - row.get("correct", 0) + 0.5 * assisted) / (n + MIN_ANSWERED_SAMPLE))

    families = {r["family_id"]: difficulty(r) for r in insights.get("families", [])}
    return {
        k: difficulty(insights["numbers"].get(n, {})) + families.get(k, 0.0)
        for k, n in catalog().items()
    }


async def progress_target(repository: Any, learner: int, insights: dict[str, Any]) -> None:
    if not await repository.personal_enabled(learner):
        return
    history = await overview(repository, learner)
    store = Session(repository, learner)
    current = await store.current()
    if current and current["problem"]:
        skill = json.loads(current["plan"])[current["position"]]
        insights["personal_tip"] = f"Продолжить тренировку · №{catalog().get(skill)}"
    elif unlocked(history):
        prefix = json.loads(current["plan"])[: current["position"]] if current else []
        slots = plan(
            history,
            catalog(),
            prefix=prefix,
            excluded=await store.excluded_for_learner(),
            support=progress_weights(insights),
            as_of=datetime.now(UTC),
        )
        if len(slots) > len(prefix):
            skill = slots[len(prefix)]
            insights["personal_tip"] = f"Для практики · №{catalog()[skill]} · {title(skill)}"


async def present(message: Message, repository: Any, learner: int) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row is None:
        return
    skills = json.loads(row["plan"])
    history = await overview(repository, learner)
    prefix = skills[: row["position"] + int(row["problem"] is not None)]
    excluded = await store.excluded_for_learner()
    strategy = str(row.get("strategy", "personal"))
    support: dict[str, float] = {}
    performance: dict[int, NumberPerformance] = {}
    if strategy == "personal":
        from app.persistence.training_insights import training_insights

        insights = await training_insights(repository, learner, "numbers")
        support = progress_weights(insights)
        performance = {
            int(key): NumberPerformance(
                int(value.get("answered_tasks", 0)), int(value.get("correct", 0))
            )
            for key, value in insights.get("numbers", {}).items()
        }
    scope = row["scope"] or {}
    if isinstance(scope, str):
        scope = json.loads(scope)
    available = catalog()
    if strategy == "number":
        available = {f: n for f, n in available.items() if n == scope.get("number")}
    exact_family = strategy == "family" or scope.get("similar_position") == row["position"]
    for _ in range(8):
        updated = skills
        if not exact_family and (strategy == "personal" or skills[row["position"]] in excluded):
            updated = plan(
                history if strategy != "mixed" else [], available, prefix=prefix, excluded=excluded,
                size=len(skills), support=support, number_performance=performance,
                seed=str(scope.get("plan_seed", row["id"])),
                as_of=datetime.now(UTC),
            )
        if len(updated) <= row["position"]:
            break
        if updated != skills and not await store.refresh(row, updated):
            return
        if row["problem"]:
            break
        skill = updated[row["position"]]
        try:
            candidate = await asyncio.to_thread(
                generate, skill, await store.seen(row["owner"], skill)
            )
        except (ValueError, RuntimeError, KeyError, OSError):
            candidate = None
        if candidate:
            if await store.save(row, skill, candidate):
                row = await store.current()
                break
            # A concurrent presentation or a newly recorded fingerprint can win.
            current = await store.current()
            if (not current or current["id"] != row["id"] or current["problem"]
                    or current["revision"] != row["revision"]):
                return
        await store.unavailable(row["owner"], skill)
        excluded.append(skill)
        skills = updated
        if exact_family:
            break
    if not row:
        return
    if not row["problem"]:
        scope = row["scope"] or {}
        if isinstance(scope, str):
            scope = json.loads(scope)
        if scope.get("similar_position") == row["position"]:
            result = await store.cancel_similar(
                row["id"], row["position"], revision=row["revision"]
            )
            if result == "exhausted":
                await feedback(
                    message, repository, learner,
                    "Новых похожих вариантов сейчас нет. Нажмите «Дальше».",
                )
            return
        result = await store.act(
            None, None, "finish", session_id=row["id"], position=row["position"],
            revision=row["revision"],
        )
        if result == "finished":
            await completion(
                message, repository, store, row, "Пока не удалось подобрать свежий вариант."
            )
        return
    data = problem_data(row)
    mode_name = {
        "personal": "Персональная",
        "mixed": "Смешанная",
        "number": f"По номеру · №{data['number']}",
        "family": title(json.loads(row["plan"])[row["position"]]),
    }.get(strategy, "Тренировка")
    await _send_problem(
        message,
        repository,
        store,
        data,
        user_id=learner,
        keyboard=keyboard(row),
        heading=f"{mode_name} · {row['position'] + 1} из {len(skills)} · №{data['number']}",
    )


def _mode_plan(
    strategy: str,
    history: History,
    *,
    number: int | None = None,
    family: str | None = None,
    excluded: list[str] | None = None,
    performance: dict[int, NumberPerformance] | None = None,
    seed: str = "0",
    as_of: datetime | None = None,
) -> list[str]:
    choices = catalog()
    if strategy == "family":
        return [family] * 5 if family in choices else []
    if strategy == "number":
        choices = {skill: n for skill, n in choices.items() if n == number}
    # The common planner also supplies a diverse diagnostic five for a new learner.
    source = [] if strategy == "mixed" else history
    return plan(
        source, choices, excluded=excluded or [], size=5,
        number_performance=performance, seed=seed,
        as_of=as_of,
    )


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
            "У вас уже сохранена короткая тренировка. Продолжить её или завершить досрочно?",
            reply_markup=markup, user_id_override=learner,
        )
        return
    if current is None:
        if store is None:
            return
        history = await overview(repository, learner)
        from app.persistence.training_insights import training_insights

        insights = await training_insights(repository, learner, "numbers")
        performance = {
            int(key): NumberPerformance(
                int(value.get("answered_tasks", 0)), int(value.get("correct", 0))
            )
            for key, value in insights.get("numbers", {}).items()
        }
        plan_seed = secrets.token_hex(8)
        skills = _mode_plan(
            strategy, history, number=number, family=family,
            excluded=await store.excluded_for_learner(),
            performance=performance, seed=plan_seed,
            as_of=datetime.now(UTC),
        )
        if not skills:
            await send_text(
                message,
                repository,
                "Сейчас нет свежих вариантов для персональной тренировки.",
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


async def trainings(message: Message, repository: Any) -> None:
    if not message.from_user:
        return
    learner = message.from_user.id
    personal_available = await repository.personal_enabled(learner)
    history = await overview(repository, learner)
    from app.persistence.training_insights import training_insights

    insights = await training_insights(repository, learner, "numbers")
    recommendations = sorted(
        (item for item in history if item[1] in catalog()
         and item[2].stage in {Stage.CHECK, Stage.GAP, Stage.PRACTICE, Stage.REOPENED}),
        key=lambda item: (
            item[2].opened <= item[2].closed,
            item[2].stage not in {Stage.GAP, Stage.PRACTICE, Stage.CHECK, Stage.REOPENED},
            -item[3].timestamp(),
        ),
    )[:2] if personal_available else []
    lines = ["Тренировки", "", "Короткая тренировка — 5 задач."]
    if recommendations:
        lines.extend(["", "Рекомендую:"])
        for number, skill, state, _ in recommendations:
            reason = stage_line(state).lower()
            number_row = insights.get("numbers", {}).get(number) or insights.get(
                "numbers", {}
            ).get(str(number), {})
            answered = int(number_row.get("answered_tasks", 0))
            if answered:
                reason += f", по №{number} верно {int(number_row.get('correct', 0))} из {answered}"
            if state.practice:
                reason += f", самостоятельное закрепление {state.practice}/{CURRENT.practice_count}"
            lines.append(f"• №{number} · {title(skill)} — {reason}.")
    elif not history and personal_available:
        lines.extend(["", "Начните с персональной диагностической пятёрки — история не требуется."])
    elif personal_available:
        lines.append("Попробуйте новые типы в персональной тренировке.")
    await repository.save_user_state(learner, "trainings")
    markup = trainings_hub(
        personal_enabled=personal_available,
        short_enabled=get_settings().oge_adaptive_enabled,
    )
    if get_settings().oge_adaptive_enabled and recommendations:
        quick = [
            button(f"№{number} · {title(skill)}", f"train:family:{skill}")
            for number, skill, _, _ in recommendations
        ]
        markup.inline_keyboard.insert(1, quick[:2])
    await send_text(
        message, repository, "\n".join(lines),
        reply_markup=markup,
        user_id_override=learner,
    )


def area_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    numbers = sorted(set(catalog().values()))
    page_count = max(1, (len(numbers) + 5) // 6)
    page = min(max(0, page), page_count - 1)
    shown = numbers[page * 6:(page + 1) * 6]
    rows = [[button(f"№{n}", f"train:area:{n}") for n in shown[i:i + 3]]
            for i in range(0, len(shown), 3)]
    arrows = []
    if page:
        arrows.append(button("←", f"train:areas:{page - 1}"))
    if page + 1 < page_count:
        arrows.append(button("→", f"train:areas:{page + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([button("↩ К тренировкам", "train:hub")])
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
        return "Пока нет проверенных навыков. Начни с задания по номеру."
    first = [s for n, _, s, _ in history if n <= 19]
    lines = [
        "Навыки и пробелы",
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
    history = sorted(
        await overview(repository, learner),
        key=lambda h: (
            h[0] >= 20,
            h[2].opened == h[2].closed,
            h[2].stage not in {Stage.CHECK, Stage.PRACTICE},
            h[2].stage == Stage.UNCHECKED,
            -h[3].timestamp(),
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
    if unlocked(history) and await repository.personal_enabled(learner):
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
    if not row or not row["problem"] or not row["prompt"] or message.message_id <= row["prompt"]:
        return
    reply = message.reply_to_message
    if reply and reply.message_id != row["prompt"]:
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
        "solved": "Верно.",
        "issued": "Пока неверно. Попробуй ещё раз.",
        "failed": "Разбор:\n\n" + _solution_text(problem),
    }[terminal_result]
    if terminal_result == "solved":
        states = {skill: state for _, skill, state, _ in await overview(repository, learner)}
        skill = json.loads(row["plan"])[row["position"]]
        state = states.get(skill)
        if state is not None and state.practice:
            text += (
                f" Самостоятельное закрепление: "
                f"{state.practice}/{CURRENT.practice_count}."
            )
    if result.startswith("completed_"):
        await send_text(
            message, repository, text, user_id_override=learner,
            math_family=problem if terminal_result == "failed" else None,
        )
        await completion(message, repository, store, row, "Тренировка завершена!")
        return
    await feedback(message, repository, learner, text)


async def feedback(message: Message, repository: Any, learner: int, text: str) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row and row["problem"]:
        sent = await send_text(
            message,
            repository,
            text,
            reply_markup=keyboard(row),
            user_id_override=learner,
            math_family=problem_data(row) if text.startswith(("Подсказка", "Разбор:")) else None,
        )
        await store.set_prompt(learner, str(row["problem"]), sent.message_id)


async def completion(
    message: Message, repository: Any, store: Session, row: Any, heading: str
) -> None:
    totals = await store.totals(row["id"])
    deltas = await store.summary_deltas(row["id"])
    lines = [
        heading,
        f"Пройдено задач: {totals['completed']} из 5.",
        f"Решено верно: {totals['solved']}/{totals['issued']}.",
        f"Самостоятельно: {totals['independent']}/{totals['issued']}.",
    ]
    if deltas:
        lines.extend(["", "Что изменилось"])
        collapsed: list[dict[str, Any]] = []
        for delta in deltas:
            item = dict(delta)
            before = item["before_state"] or {}
            previous_after = collapsed[-1]["after_state"] if collapsed else None
            if isinstance(before, str):
                before = json.loads(before)
            if isinstance(previous_after, str):
                previous_after = json.loads(previous_after)
            if (
                collapsed
                and collapsed[-1]["skill"] == item["skill"]
                and previous_after == before
            ):
                collapsed[-1]["after_state"] = item["after_state"]
            else:
                collapsed.append(item)
        for delta in collapsed[:5]:
            before = delta["before_state"] or {}
            after = delta["after_state"] or {}
            if isinstance(before, str):
                before = json.loads(before)
            if isinstance(after, str):
                after = json.loads(after)
            old = int(before.get("practice", 0))
            new = int(after.get("practice", 0))
            detail = (
                f"самостоятельное закрепление {old}/{CURRENT.practice_count} "
                f"→ {new}/{CURRENT.practice_count}"
            )
            if before.get("stage") != after.get("stage"):
                status = stage_line(State(
                    stage=after.get("stage", Stage.UNCHECKED),
                    practice=int(after.get("practice", 0)),
                    opened=int(after.get("opened", 0)),
                    closed=int(after.get("closed", 0)),
                ))
                detail = f"{status}; {detail}"
            lines.append(f"• {title(delta['skill'])}: {detail}.")
    lines.extend(["", "Что дальше"])
    personal_available = await repository.personal_enabled(store.learner)
    final_history = await overview(repository, store.learner) if personal_available else []
    remaining = sorted(
        (item for item in final_history if item[1] in catalog()
         and item[2].stage in {Stage.CHECK, Stage.GAP, Stage.PRACTICE, Stage.REOPENED}),
        key=lambda item: (
            item[2].opened <= item[2].closed,
            item[2].stage not in {Stage.GAP, Stage.REOPENED, Stage.PRACTICE, Stage.CHECK},
            -item[3].timestamp(),
        ),
    )
    focus = remaining[0][1] if remaining else None
    if remaining:
        lines.append(
            f"Рекомендую: {title(remaining[0][1])} — {stage_line(remaining[0][2]).lower()}."
        )
    elif personal_available:
        lines.append("Можно начать новую персональную тренировку или выбрать номер.")
    else:
        lines.append("Можно выбрать короткую тренировку по номеру или смешанную пятёрку.")
    text = "\n".join(lines)
    rows = [
            *([[button("Потренировать этот тип", f"train:family:{focus}")]] if focus else []),
            [button("Мой прогресс", "train:progress")],
            [button("В меню", "nav:main")],
    ]
    rows.insert(0, [button(
        "Новая персональная" if personal_available else "Смешанная · 5 задач",
        "train:personal" if personal_available else "train:mixed",
    )])
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
            await answer_callback(cb, "Это меню устарело. Откройте тренировки снова.")
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
            page = int(parts[2]) if len(parts) == 3 else 0
            await send_text(actor_message, repository, "Выберите номер для короткой тренировки.",
                            reply_markup=area_keyboard(page), user_id_override=learner)
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
                    cb, "Персональная тренировка выключена. Выберите другой режим."
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
        or row["problem"]
        and row["prompt"] != cb.message.message_id
    ):
        await answer_callback(cb, "Это задание уже сменилось.")
        return
    action = parts[1]
    if action == "retry":
        await present(cb.message, repository, learner)
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
            reply_markup=main_menu(),
            user_id_override=learner,
        )
    elif action == "similar":
        result = await store.choose_similar(
            row["id"], row["position"], row["problem"], revision=row.get("revision")
        )
        if result == "next":
            await present(cb.message, repository, learner)
        elif result == "full":
            await completion(cb.message, repository, store, row, "Тренировка завершена!")
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
                "Разбор:\n\n" + _solution_text(problem)
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
                "solution": "Разбор:\n\n" + _solution_text(p),
                "no_hint": "Подсказок больше нет.",
            }.get(result)
            await feedback(
                cb.message,
                repository,
                learner,
                text or hint_message(p["hints"][row["hints_used"]], p),
            )
    await answer_callback(cb)
