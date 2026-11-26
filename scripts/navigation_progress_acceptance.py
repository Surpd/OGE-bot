"""Capture progress navigation through a local PostgreSQL-backed Telegram dispatcher."""
import asyncio

from scripts import live_training_acceptance as live


async def exercise(h):
    session = live.Session(h.repository, 42)
    await h.click("nav:trainings")
    await h.click("train:areas")
    await h.click("train:area:6")
    await h.click("train:number:6")
    for i in range(8):
        active = await session.current()
        answer = str(live.problem_data(active)["correct_answer"])
        if i != 7:
            await h.message("1" if answer != "1" else "2")
        await h.message(answer)
        if i != 7:
            action = "continue" if i == 4 else "next"
            await h.click(f"ad:{action}:{active['problem']}")
    await h.click(f"ad:finish:{active['problem']}")
    await h.message("/start")
    report = live.Report(h)

    async def click(action, case, label):
        await h.click(action)
        await report.mark(case, label)

    await click("nav:progress", "home", "Мой прогресс")
    await click("progress:works:0", "written", "Письменные работы")
    await h.click("progress:summary")
    await click("progress:details", "numbers", "Подробнее по номерам")
    await click("progress:number:6", "number", "Результаты и типы №6")
    await click("progress:family:6:0", "catalog", "Каталог типов №6")
    await h.click("progress:number:6")
    await click("progress:numhist:6:0", "number-journal", "Журнал №6")
    await click("progress:numerr:6:0", "number-errors", "Ошибки №6")
    await click("progress:numerr:6:6", "page-two", "Вторая страница ошибок №6")
    message = h.button("progress:filter:n6.6")[0]
    item = next(b.callback_data.partition("~")[0] for row in message.reply_markup.inline_keyboard
                for b in row if b.callback_data.startswith("progress:item:"))
    await click(item, "record", "Исходное задание, попытки и действия")
    await click(item.replace(":item:", ":solution:"), "solution", "Разбор исходного задания")
    await click("progress:numerr:6:6", "return", "Возврат на вторую страницу ошибок №6")
    await click("progress:filter:n6.6", "filters", "Выбор номера журнала")
    await click("progress:errors:0", "all-errors", "Ошибки по всем номерам")
    await click("progress:history:0", "all-tasks", "Все задания по всем номерам")
    await h.click("progress:summary")
    await h.click("progress:details")
    await h.click("progress:number:6")
    await click("train:number:6", "practice", "Запуск тренировки из детализации №6")
    report.write()


if __name__ == "__main__":
    live.OUT = live.ROOT / "reports/navigation-rotation/progress"
    asyncio.run(live.run_with_synthetic_user(exercise))
