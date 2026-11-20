"""Read-only score details and private, revision-specific written work."""

import json

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.bot.part2 import keyboard, store
from app.bot.presentation import send_text
from app.persistence.part2_insights import history, revision, summary
from app.persistence.repository import Repository


async def page(message: Message, repo: Repository, owner: int, parts: list[str]) -> None:
    bank = store(repo)
    rows = []
    message_text = "Запись недоступна."
    if (
        bank
        and message.chat.type == "private"
        and all(x.isascii() and x.isdigit() and len(x) <= 18 for x in parts[1:])
    ):
        if parts[0] == "written" and len(parts) == 2:
            number = int(parts[1])
            values = (await summary(bank.pool, owner)).get(number, {})
            def g(key: str) -> int:
                return int(values.get(key, 0))
            message_text = (
                f"№{number} · предварительные оценки GPT\n\n"
                f"Выдано: {g('issued')}. Без оценки: {g('unchecked')}. Подсказок: {g('hints')}.\n"
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
            rows.append([("История письменных работ", "progress:works:0")])
        elif parts[0] == "works" and len(parts) == 2:
            offset = min(2**31 - 1, int(parts[1]))
            issues = await history(bank.pool, owner, offset)
            lines = ["Письменные работы"]
            for idx, r in enumerate(issues[:6], offset + 1):
                lines.append(f"{idx}. №{r['number']} · {r['title']} · {r['issued_at']:%d.%m.%Y}")
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
                lines = [f"№{r['number']} · работа {attempt}", r["statement"]]
                for piece in work:
                    if piece["body"]:
                        lines.append(piece["body"])
                    if piece["photo"]:
                        try:
                            await message.answer_photo(piece["photo"])
                        except TelegramBadRequest:
                            lines.append("Фото уже недоступно.")
                if not work:
                    lines.append("Материалов этой версии нет или срок хранения истёк.")
                if r["result"]:
                    report = json.loads(r["result"])
                    if r["score"] is not None:
                        lines.append(f"Предварительная оценка GPT: {r['score']}/2")
                    lines.extend([report["feedback"], *report["errors"], report["next_step"]])
                elif r["status"]:
                    lines.append("Проверка не завершена. Балл не выставлен.")
                else:
                    lines.append("Черновик.")
                for line in lines[:-1]:
                    if line:
                        await message.answer(line, parse_mode=None)
                message_text = lines[-1] or "Конец работы."
                arrows = []
                if attempt > 1:
                    arrows.append(
                        ("Предыдущая версия", f"progress:work:{issue}:{attempt - 1}:{offset}")
                    )
                if attempt < r["revision"]:
                    arrows.append(
                        ("Следующая версия", f"progress:work:{issue}:{attempt + 1}:{offset}")
                    )
                if arrows:
                    rows.append(arrows)
            rows.append([("К письменным работам", f"progress:works:{offset}")])
    rows.append([("Мой прогресс", "progress:summary")])
    await send_text(
        message, repo, message_text, reply_markup=keyboard(rows), user_id_override=owner
    )
