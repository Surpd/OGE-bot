"""Read-only score details and private, revision-specific written work."""

import asyncio
import json

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, Message

from app.bot.explicit_math import display_feedback
from app.bot.part2 import image_bytes, keyboard, store
from app.bot.presentation import has_mathematics, send_text
from app.persistence.part2_insights import history, revision, summary
from app.persistence.repository import Repository


async def page(
    message: Message, repo: Repository, owner: int, parts: list[str], *, resume_issue: bool = False
) -> None:
    bank = store(repo)
    feedback_template = None
    rows = []
    message_text = "Запись недоступна."
    if (
        bank
        and message.chat.type == "private"
        and all(x.isascii() and x.isdigit() and len(x) <= 18 for x in parts[1:])
    ):
        if parts[0] == "written" and len(parts) == 2 and int(parts[1]) in range(20, 26):
            number = int(parts[1])
            values = (await summary(bank.pool, owner)).get(number, {})

            def g(key: str) -> int:
                return int(values.get(key, 0))

            message_text = (
                f"№{number} · предварительные оценки GPT\n\n"
                f"Выдано: {g('issued')}. Пропущено: {g('skipped')}. "
                f"Повторных задач: {g('repeated')}. Подсказок: {g('hints')}.\n"
                f"Первая работа: полных баллов {g('first_full')}/{g('first_graded')}, "
                f"сумма баллов {g('first_points')}.\n"
                f"Все проверки с баллом: {g('checked')}. Повторных отправок: {g('revisions')}.\n"
                f"0 баллов: {g('zeros')}, 1 балл: {g('ones')}, 2 балла: {g('twos')}. "
                f"Сумма: {g('points')}.\n"
                f"Неоднозначных и нечитаемых: {g('unclear')}. "
                f"Ожидают или недоступны: {g('unavailable')}."
            )
            for item in values.get("subtypes", []):
                message_text += (
                    f"\n{item['title']}: {item['first_full']}/{item['first_graded']} на 2 балла"
                )
            from app.config import get_settings

            if get_settings().oge_adaptive_enabled:
                from app.adaptive.engine import Stage, family_status
                from app.adaptive.skills import title as skill_title
                from app.adaptive.store import overview

                states = [
                    (skill, state) for n, skill, state, _ in await overview(repo, owner)
                    if n == number and state.stage != Stage.UNCHECKED
                ]
                for index, (skill, state) in enumerate(states, start=1):
                    status = family_status(state).label
                    message_text += f"\n{index}. {skill_title(skill)} · {status}"
                    if state.stage != Stage.CONFIRMED:
                        rows.append([(f"Тренировать тип {index}", f"p2:open:{number}:{skill}")])
            rows.append([("История письменных работ", "progress:works:0")])
        elif parts[0] == "works" and len(parts) == 2:
            offset = min(2**31 - 1, int(parts[1]))
            issues = await history(bank.pool, owner, offset)
            lines = ["Письменные работы"]
            for idx, r in enumerate(issues[:6], offset + 1):
                repetition = " · повтор" if r["repeat_kind"] else ""
                lines.append(
                    f"{idx}. №{r['number']} · {r['title']}\n"
                    f"{r['issued_at']:%d.%m.%Y} · {r['outcome']}{repetition}"
                )
            if not issues:
                lines.append("Здесь появятся ваши задания №20–25.")
            for ix in range(0, min(len(issues), 6), 3):
                rows.append(
                    [
                        (str(offset + j + 1), f"progress:work:{issues[j]['id']}:1:{offset}")
                        for j in range(ix, min(ix + 3, len(issues), 6))
                    ]
                )
            arrows = []
            if offset:
                arrows.append(("←", f"progress:works:{max(0, offset - 6)}"))
            if len(issues) > 6:
                arrows.append(("→", f"progress:works:{offset + 6}"))
            if arrows:
                rows.append(arrows)
            message_text = "\n\n".join(lines)
        elif parts[0] == "work" and len(parts) == 4:
            issue, attempt, offset = map(int, parts[1:])
            record = await revision(bank.pool, owner, issue, attempt)
            if record:
                r, work = record
                from app.bot.part2_check import grading_reply
                from app.part2_grading import Assessment

                lines = []
                repetition = "\nПовторная тренировка" if r["repeat_kind"] else ""
                title = f"№{r['number']} · Работа {attempt}{repetition}"
                for visual in json.loads(r["visuals"]):
                    if visual["role"] != "condition":
                        continue
                    try:
                        data = await asyncio.to_thread(image_bytes, visual)
                        await message.answer_photo(
                            BufferedInputFile(data, filename="condition.png")
                        )
                    except (OSError, ValueError, TelegramBadRequest):
                        lines.append("Исходный рисунок сейчас недоступен.")
                await send_text(
                    message,
                    repo,
                    f"{title}\n\n{r['statement']}",
                    rich_with_navigation=True,
                    math_family=r["subtype_id"],
                )
                for piece in work:
                    if piece["body"]:
                        await send_text(
                            message,
                            repo,
                            "Ваше решение\n\n" + display_feedback(piece["body"]),
                        )
                    if piece["expired"]:
                        lines.append("Срок хранения фотографии истёк.")
                    if piece["photo"]:
                        try:
                            await message.answer_photo(piece["photo"])
                        except TelegramBadRequest:
                            lines.append("Фото уже недоступно.")
                if not work:
                    lines.append("Материалов этой версии нет или срок хранения истёк.")
                if r["result"]:
                    report = json.loads(r["result"])
                    report = dict(report)
                    for key in ("model_id", "prompt_version", "rubric_version"):
                        report.pop(key, None)
                    if "criterion_evidence" in report:
                        lines.append(
                            grading_reply(
                                Assessment.model_validate(report),
                                r["rubric_kind"] or "",
                            )
                        )
                    else:
                        if r["score"] is not None:
                            lines.append(f"Оценка: {r['score']} из 2 баллов (предварительная)")
                        lines.append(display_feedback(report["feedback"]))
                        if r["score"] != 2:
                            lines.append(display_feedback(report["next_step"]))
                elif r["status"] == "pending":
                    lines.append("Работа проверяется. Балл пока не выставлен.")
                elif r["status"]:
                    lines.append("Проверка не завершена. Балл не выставлен.")
                elif r["skipped_at"]:
                    lines.append("Задача пропущена.")
                elif r["solution_viewed_at"]:
                    lines.append("Разбор открыт.")
                elif r["closed"]:
                    lines.append("Работа завершена.")
                else:
                    lines.append("Черновик.")
                lines.append("Задача закрыта." if r["closed"] else "Задача открыта.")
                message_text = "\n\n".join(line for line in lines if line)
                if r["result"] and has_mathematics(message_text):
                    feedback_template = "written-feedback"
                arrows = []
                if attempt > 1:
                    arrows.append(
                        ("Предыдущая версия", f"progress:work:{issue}:{attempt - 1}:{offset}")
                    )
                if attempt < (r["last_work"] or 0):
                    arrows.append(
                        ("Следующая версия", f"progress:work:{issue}:{attempt + 1}:{offset}")
                    )
                if arrows:
                    rows.append(arrows)
            if resume_issue and record:
                rows.append([("К заданию", f"p2:resume:{issue}"), ("К номерам", "nav:numbers")])
            else:
                rows.append([("К письменным работам", f"progress:works:{offset}")])
    if not resume_issue:
        rows.append([("Мой прогресс", "progress:summary")])
    await send_text(
        message,
        repo,
        message_text,
        reply_markup=keyboard(rows),
        user_id_override=owner,
        rich_with_navigation=True,
        math_family=feedback_template,
    )
