import asyncio
import json
import secrets
from functools import lru_cache
from typing import Any
from uuid import uuid4

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.adaptive.engine import CURRENT, Stage, State
from app.adaptive.planner import History, plan, unlocked
from app.adaptive.session import Session
from app.adaptive.skills import title
from app.adaptive.sources import scenario_variant
from app.adaptive.store import overview
from app.bot.callbacks import answer_callback
from app.bot.menu import main_menu
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
        rows.append([action("Далее", "next")])
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
    from app.persistence.training_insights import training_insights

    support = progress_weights(await training_insights(repository, learner, "numbers"))
    for _ in range(8):
        updated = plan(
            history, catalog(), prefix=prefix, excluded=excluded, size=len(skills), support=support
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
        except (ValueError, RuntimeError, KeyError):
            candidate = None
        if candidate:
            if not await store.save(row, skill, candidate):
                return
            row = await store.current()
            break
        await store.unavailable(row["owner"], skill)
        excluded.append(skill)
        skills = updated
    if not row:
        return
    if not row["problem"]:
        result = await store.act(
            None, None, "finish", session_id=row["id"], position=row["position"]
        )
        if result == "finished":
            await completion(
                message, repository, store, row, "Пока не удалось подобрать свежий вариант."
            )
        return
    data = problem_data(row)
    await _send_problem(
        message,
        repository,
        store,
        data,
        user_id=learner,
        keyboard=keyboard(row),
        heading=f"Персональная · {row['position'] + 1} из {len(skills)} · №{data['number']}",
    )


async def start(message: Message, repository: Any) -> None:
    if not get_settings().oge_adaptive_enabled or not message.from_user:
        return
    learner = message.from_user.id
    if not await repository.personal_enabled(learner):
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
    if current is None:
        history = await overview(repository, learner)
        if not unlocked(history) or store is None:
            await send_text(
                message,
                repository,
                "Для плана нужны результаты обычных тренировок.",
                reply_markup=main_menu(),
                user_id_override=learner,
            )
            return
        skills = plan(history, catalog(), excluded=await store.excluded_for_learner())
        if not skills:
            await send_text(
                message,
                repository,
                "Сейчас нет свежих вариантов для персональной тренировки.",
                reply_markup=main_menu(),
                user_id_override=learner,
            )
            return
        await store.start(skills)
    elif store:
        await store.start([])
    await present(message, repository, learner)


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


_LABEL = {
    Stage.UNCHECKED: "Ещё не проверено",
    Stage.CHECK: "Нужна самостоятельная проверка",
    Stage.GAP: "Обнаружен пробел",
    Stage.PRACTICE: "Закрепляется",
    Stage.CONFIRMED: "Уверенно решаешь сейчас",
    Stage.REOPENED: "Повторное закрепление",
}


def stage_line(s: State) -> str:
    if s.stage == Stage.CONFIRMED and s.closed:
        return "Пробел закрыт"
    return _LABEL[Stage(s.stage)]


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
    if await repository.user_state(learner) != "adaptive" or not await repository.personal_enabled(
        learner
    ):
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
    )
    if result == "stale":
        return
    text = {
        "solved": "Верно.",
        "issued": "Пока неверно. Попробуй ещё раз.",
        "failed": "Разбор:\n\n" + "\n".join(problem.get("solution", [])),
    }[result]
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
    text = (
        f"{heading}\nРешено {totals['solved']} из {totals['issued']} выданных. "
        f"С первой попытки без помощи · {totals['independent']}."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Ещё одна тренировка", "nav:adaptive")],
            [button("В меню", "nav:main")],
        ]
    )
    await send_text(
        message, repository, text, reply_markup=keyboard, user_id_override=store.learner
    )


async def callback(cb: CallbackQuery, repository: Any) -> None:
    if not get_settings().oge_adaptive_enabled or not isinstance(cb.message, Message):
        await answer_callback(cb)
        return
    learner = cb.from_user.id
    if not await repository.personal_enabled(learner):
        await answer_callback(cb, "Режим выключен в настройках.")
        return
    store = Session(repository, learner)
    row = await store.current()
    parts = (cb.data or "").split(":")
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
            row["problem"], row["prompt"], "menu", session_id=row["id"], position=row["position"]
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
    else:
        result = await store.act(
            row["problem"], row["prompt"], action, session_id=row["id"], position=row["position"]
        )
        if result in {"finished", "completed"}:
            await completion(cb.message, repository, store, row, "Тренировка завершена.")
        elif result == "next":
            await present(cb.message, repository, learner)
        elif result in {"hint", "skip", "solution", "no_hint"}:
            p = problem_data(row)
            text = {
                "skip": "Задание пропущено.",
                "solution": "Разбор:\n\n" + "\n".join(p.get("solution", [])),
                "no_hint": "Подсказок больше нет.",
            }.get(result)
            await feedback(
                cb.message,
                repository,
                learner,
                text or hint_message(p["hints"][row["hints_used"]], p),
            )
    await answer_callback(cb)
