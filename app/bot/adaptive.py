import asyncio
import json
import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.adaptive.engine import V1, Stage, State
from app.adaptive.planner import History, plan, unlocked
from app.adaptive.session import Session
from app.adaptive.skills import title
from app.adaptive.sources import scenario_variant
from app.adaptive.store import overview
from app.bot.callbacks import answer_callback
from app.bot.menu import main_menu
from app.bot.mixed_training import _is_correct, _scenario_question, _send_problem
from app.bot.presentation import send_text
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
    if row["problem"]:
        if row["outcome"] == "issued":
            rows.append([action("Подсказка", "hint"), action("Разбор", "solution")])
            rows.append([action("Пропустить", "skip")])
        else:
            rows.append([action("Далее", "next")])
    else:
        rows.append([action("Попробовать снова", "retry"), action("Дальше", "omit")])
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


async def present(message: Message, repository: Any, learner: int) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row is None:
        return
    skills = json.loads(row["plan"])
    skill = skills[row["position"]]
    if not row["problem"] or row["outcome"] == "issued":
        history = await overview(repository, learner)
        state = next((s for _, key, s, _ in history if key == skill), State())
        if (
            state.stage == Stage.CONFIRMED
            or state.due
            and (
                state.due > datetime.now(UTC).timestamp()
                or row["issued_at"]
                and row["issued_at"].timestamp() < state.due
            )
        ):
            result = await store.act(
                row["problem"],
                row["prompt"],
                "fulfilled",
                session_id=row["id"],
                position=row["position"],
            )
            if result == "next":
                await present(message, repository, learner)
            elif result == "completed":
                await send_text(
                    message,
                    repository,
                    "План завершён. Решения из других тренировок учтены.",
                    reply_markup=main_menu(),
                    user_id_override=learner,
                )
            return
    if not row["problem"]:
        try:
            candidate = await asyncio.to_thread(
                generate, skill, await store.seen(row["owner"], skill)
            )
        except (ValueError, RuntimeError, KeyError):
            candidate = None
        if not candidate:
            await send_text(
                message,
                repository,
                "Новый вариант этого типа пока недоступен. Проверка останется в плане.",
                reply_markup=keyboard(row),
                user_id_override=learner,
            )
            return
        if not await store.save(row, skill, candidate):
            return
        row = await store.current()
        if not row:
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
        await store.start(plan(history, catalog(), datetime.now(UTC).timestamp()))
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
    Stage.WAIT: "Ожидает проверки",
    Stage.CONFIRMED: "Навык подтверждён",
    Stage.REOPENED: "Повторное закрепление",
}


def stage_line(s: State) -> str:
    if s.stage == Stage.CONFIRMED and s.closed:
        return "Пробел закрыт"
    return _LABEL[Stage(s.stage)]


def summary(history: History, now: float, offset: int = 0) -> str:
    if not history:
        return "Пока нет проверенных навыков. Начни с задания по номеру."
    due = sum(s.due is not None and s.due <= now for _, _, s, _ in history)
    lines = [
        "Навыки и пробелы",
        f"Открыто пробелов · {sum(s.opened > s.closed for _, _, s, _ in history)}",
        f"Проверок на сегодня · {due}",
        f"Закрыто пробелов · {sum(s.closed for _, _, s, _ in history)}",
        f"На закреплении · {sum(s.stage == Stage.PRACTICE for _, _, s, _ in history)}",
        f"Предстоящих проверок · {sum(bool(s.due and s.due > now) for _, _, s, _ in history)}",
        f"Повторно открыто · {sum(max(0, s.opened - 1) for _, _, s, _ in history)}",
        f"Требуют проверки · {sum(s.stage == Stage.CHECK for _, _, s, _ in history)}",
    ]
    for number, skill, s, _ in history[offset : offset + 1]:
        label = title(skill)
        lines.extend(["", f"№{number} · {label}", stage_line(s)])
        if s.opened or s.practice:
            lines.append(
                f"Самостоятельные решения {s.practice}/{V1.practice_count} · "
                f"проверки {s.checks}/{len(V1.intervals_days)}"
            )
        if s.due:
            date = datetime.fromtimestamp(s.due, UTC).strftime("%d.%m.%Y %H:%M UTC")
            lines.append("Можно проверить сейчас" if s.due <= now else f"Следующая проверка {date}")
        if number >= 20 and s.stage != Stage.CONFIRMED:
            lines.append("Для проверки выбери новую письменную работу этого подтипа.")
    return "\n".join(lines)


async def gaps(message: Message, repository: Any, offset: int = 0) -> None:
    if not get_settings().oge_adaptive_enabled or not message.from_user:
        return
    learner = message.from_user.id
    history = await overview(repository, learner)
    rows = []
    for number, skill, state, _ in history[offset : offset + 1]:
        if (
            number >= 20
            and state.stage not in {Stage.UNCHECKED, Stage.CONFIRMED}
            and get_settings().oge_part2_enabled
        ):
            rows.append([button(f"Письменная работа №{number}", f"p2:open:{number}:{skill}")])
    if unlocked(history):
        rows.append([button("Персональная тренировка", "nav:adaptive")])
    body = summary(history, datetime.now(UTC).timestamp(), offset)
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
                "check_passed": "проверка пройдена",
                "gap_closed": "пробел закрыт",
                "practice_complete": "назначена проверка",
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
            if (
                remaining
                < max(0, V1.practice_count - state.practice) + len(V1.intervals_days) - state.checks
            ):
                body += "\nДля полного цикла потребуется проверка новых работ преподавателем."
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
    )
    if result == "stale":
        return
    text = {
        "solved": "Верно.",
        "issued": "Пока неверно. Попробуй ещё раз.",
        "failed": "Разбор\n" + "\n".join(problem.get("solution", [])),
    }[result]
    await feedback(message, repository, learner, text)


async def feedback(message: Message, repository: Any, learner: int, text: str) -> None:
    store = Session(repository, learner)
    row = await store.current()
    if row and row["problem"]:
        sent = await send_text(
            message, repository, text, reply_markup=keyboard(row), user_id_override=learner
        )
        await store.set_prompt(learner, str(row["problem"]), sent.message_id)


async def callback(cb: CallbackQuery, repository: Any) -> None:
    if not get_settings().oge_adaptive_enabled or not isinstance(cb.message, Message):
        await answer_callback(cb)
        return
    learner = cb.from_user.id
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
            await send_text(
                cb.message,
                repository,
                "Тренировка завершена.",
                reply_markup=main_menu(),
                user_id_override=learner,
            )
        elif result == "next":
            await overview(repository, learner)
            await present(cb.message, repository, learner)
        elif result in {"hint", "skip", "solution", "no_hint"}:
            p = problem_data(row)
            text = {
                "skip": "Задание пропущено.",
                "solution": "\n".join(p.get("solution", [])),
                "no_hint": "Подсказок больше нет.",
            }.get(result)
            await feedback(cb.message, repository, learner, text or p["hints"][row["hints_used"]])
    await answer_callback(cb)
