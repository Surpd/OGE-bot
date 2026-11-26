"""Capture actual optional cards through the companion dispatcher and local PostgreSQL."""

# Reuse the companion's existing synthetic transport and Bot API serializer.
# ruff: noqa: E402
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from html import escape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import asyncpg
from PIL import Image
from test_companion_qa import Harness, config

from app.adaptive.session import Session
from app.bot.adaptive import problem_data
from app.bot.visual_cards import render_card
from app.bot.visual_models import (
    VisualBreakdown,
    VisualCard,
    VisualEntry,
    VisualMetric,
    VisualPractice,
    VisualSection,
)
from app.companion.storage import open_storage
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository
from scripts.live_training_acceptance import card, serialize

OUT = ROOT / "reports" / "visual-cards"
WIDTHS = (360, 390, 430)


class Evidence:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.cursor = 0
        self.cases: list[dict] = []

    def reset(self) -> None:
        self.cursor = len(self.harness.transport.calls)

    def sizes(self, asset: str) -> dict[int, int]:
        with Image.open(OUT / asset) as image:
            assert image.width == 1200 and image.height <= 2700
            return {width: round(image.height * width / image.width) for width in WIDTHS}

    async def mark(self, name: str, label: str, expected_screen: str) -> None:
        calls = self.harness.transport.calls[self.cursor:]
        self.reset()
        branded = []
        for method in calls:
            photo = method.photo if method.__api_method__ == "sendPhoto" else (
                method.media.media if method.__api_method__ == "editMessageMedia" else None
            )
            if getattr(photo, "filename", "") == f"bop-{expected_screen}.png":
                branded.append(method)
        assert len(branded) == 1, (name, [method.__api_method__ for method in calls])
        call = await serialize(self.harness.transport, self.harness.bot, branded[0], out=OUT)
        asset = next(iter(call["attachments"].values()))
        displayed = self.sizes(asset["path"])
        self.cases.append({
            "name": name, "label": label, "call": call, "displayed_heights": displayed,
        })
        print(name, displayed, flush=True)

    def aggregate(self, name: str, label: str, visual: VisualCard, *, origin: str) -> None:
        png = render_card(visual)
        digest = hashlib.sha256(png).hexdigest()
        asset = f"assets/{digest}.png"
        (OUT / asset).parent.mkdir(parents=True, exist_ok=True)
        (OUT / asset).write_bytes(png)
        self.cases.append({
            "name": name, "label": label, "asset": asset, "source": origin,
            "displayed_heights": self.sizes(asset),
        })

    async def mark_text_fallback(self) -> None:
        calls = self.harness.transport.calls[self.cursor:]
        self.reset()
        text_calls = [method for method in calls if method.__api_method__ == "sendMessage"]
        assert len(text_calls) == 1 and not any(
            method.__api_method__ == "sendPhoto" for method in calls
        )
        call = await serialize(self.harness.transport, self.harness.bot, text_calls[0], out=OUT)
        assert "Решено верно" in call["payload"]["text"] and "→" not in call["payload"]["text"]
        self.cases.append({
            "name": "text-fallback", "label": "Текстовый резерв при отказе рендера",
            "call": call, "displayed_heights": {},
        })

    def write(self) -> None:
        (OUT / "payloads").mkdir(parents=True, exist_ok=True)
        sections = []
        for item in self.cases:
            name = item["name"]
            if "call" in item:
                (OUT / "payloads" / f"{name}.json").write_text(
                    json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                body = (
                    f'<p><a href="payloads/{name}.json">Payload Bot API</a></p>'
                    f'{card(item["call"])}'
                )
            else:
                body = (
                    f'<p>{escape(item["source"])}</p>'
                    f'<img src="{item["asset"]}" alt="{escape(item["label"])}">'
                )
            sections.append(
                f'<section id="{name}"><h2>{escape(item["label"])}</h2>{body}</section>'
            )
        (OUT / "manifest.json").write_text(
            json.dumps([
                {key: value for key, value in item.items() if key != "call"} for item in self.cases
            ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        (OUT / "index.html").write_text(
            '<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>bop Math · приёмка PNG</title>'
            '<style>'
            '*{box-sizing:border-box}body{margin:0;color:#1f3531;background:#e8ede5;'
            'font:15px/1.45 system-ui,sans-serif}header{background:#213c34;color:white;'
            'padding:16px}h1{font-size:24px;margin:0}header p{margin:7px 0 0}nav{padding:12px 16px}'
            'main{width:min(100%,var(--card-width,430px));margin:auto}section{margin:0 0 20px;'
            'padding:12px 0;background:#f7f7f1}h2{font-size:17px;margin:0 12px}section>p{margin:'
            '3px 12px 10px}.row{display:flex;gap:3px;margin:3px 4px}.row span{flex:1;min-width:0;'
            'text-align:center;padding:7px 4px;background:#355846;color:white;border-radius:4px;'
            'font-size:13px;overflow-wrap:anywhere}img{width:100%;height:auto;display:block}'
            'article>small{display:block;margin:6px 12px}article .text:empty{display:none}'
            '</style><header><h1>bop Math · приёмка PNG</h1>'
            '<p>Локальный companion, синтетический ученик и PostgreSQL.</p></header>'
            '<nav><label>Ширина PNG <select id="width"><option>360</option><option>390</option>'
            '<option selected>430</option></select> px</label></nav><main>'
            + "".join(sections)
            + '</main><script>document.querySelector("#width").addEventListener("change",event=>'
            'document.documentElement.style.setProperty("--card-width",event.target.value+"px"))'
            '</script></html>',
            encoding="utf-8",
        )


def aggregate_examples(report: Evidence) -> None:
    def result(
        title: str, outcomes: VisualBreakdown, practice: tuple[VisualPractice, ...] = (),
        review: str = "", *, subtitle: str = "5 задач",
    ) -> VisualCard:
        correct = outcomes.independent + outcomes.assisted
        return VisualCard(
            "training_result", title, subtitle,
            sections=(VisualSection("Что повторить", (VisualEntry(review),)),) if review else (),
            metrics=(
                VisualMetric(f"{correct} из {outcomes.total}", "Решено верно", "good"),
                VisualMetric(f"{outcomes.independent} из {outcomes.total}", "Самостоятельно"),
            ),
            breakdown=outcomes, practice=practice,
        )

    checkpoint = "Промежуточный итог"
    finish = "Тренировка завершена"
    feedback = "Агрегированные результаты из обратной связи первого дня."
    report.aggregate("day-one-a", "Пример А · первые пять", result(
        checkpoint, VisualBreakdown(3, 2, 0, 0),
        (VisualPractice("Медиана к гипотенузе по клеткам", 2, 3),),
    ), origin=feedback)
    report.aggregate("day-one-b", "Пример Б · первые пять", result(
        checkpoint, VisualBreakdown(3, 0, 2, 0),
    ), origin=feedback)
    report.aggregate("day-one-c", "Пример В · итог тренировки", result(
        finish, VisualBreakdown(1, 0, 3, 1),
        (VisualPractice("Какой корень принадлежит отрезку", 1, 3),), "№19 · Прямые и углы",
    ), origin=feedback)
    edge = "Синтетический сценарий для проверки отображения."
    report.aggregate("all-correct", "Идеальный результат", result(
        finish, VisualBreakdown(5, 0, 0, 0),
        (VisualPractice("Медиана к гипотенузе по клеткам", 3, 3, confirmed=True),),
    ), origin=edge)
    report.aggregate("zero-correct", "Ни одного верного ответа", result(
        finish, VisualBreakdown(0, 0, 4, 1),
    ), origin=edge)


async def exercise(h: Harness, report: Evidence) -> None:
    async def pick(action, name, label, screen):
        report.reset()
        await h.click(action)
        await report.mark(name, label, screen)

    await h.message("/start")
    await pick("exit", "welcome", "Главное меню", "welcome")
    await h.click("nav:trainings")
    await pick("train:areas", "numbers", "Номера первой части", "numbers")
    await pick("train:areas:1", "part2", "Номера второй части", "part2")
    await h.click("train:areas:0")
    await pick("train:area:2", "stories", "Сюжеты №2", "stories")
    await pick("train:story:2:FLAT", "story-types", "Квартиры · типы №2", "types")
    await h.click("train:area:2")
    await h.click("train:areas")
    await pick("train:area:6", "types", "Вычисления · типы №6", "types")

    session = Session(h.repository, 42)

    async def answer_current():
        row = await session.current()
        answer = str(problem_data(row)["correct_answer"])
        await h.message(answer)
        return row

    await h.click("train:number:6")
    for index in range(5):
        if index == 4:
            report.reset()
        row = await answer_current()
        if index < 4:
            await h.click(f"ad:next:{row['problem']}")
    await report.mark("checkpoint", "Длительная практика · первые пять", "training-result")
    await h.click(f"ad:continue:{row['problem']}")
    for index in range(5):
        if index == 4:
            report.reset()
        row = await answer_current()
        if index < 4:
            await h.click(f"ad:next:{row['problem']}")
    await report.mark("checkpoint-2", "Длительная практика · вторые пять", "training-result")
    await h.click(f"ad:continue:{row['problem']}")
    row = await answer_current()
    await pick(f"ad:finish:{row['problem']}", "long-result",
               "Длительная практика · завершение", "training-result")

    await h.message("/start")
    await h.click("nav:progress")
    await h.click("progress:details")
    await pick("progress:number:6", "number-progress", "Прогресс по №6", "number-progress")

    for strategy, label in (("mixed", "Смешанная"), ("personal", "Персональная")):
        await h.message("/start")
        await h.click("nav:trainings")
        await h.click(f"train:{strategy}")
        for index in range(5):
            if index == 4:
                report.reset()
            row = await answer_current()
            if index < 4:
                await h.click(f"ad:next:{row['problem']}")
        await report.mark(f"{strategy}-result", f"{label} тренировка · итог", "training-result")

    await h.message("/start")
    await h.click("nav:trainings")
    await h.click("train:areas")
    await h.click("train:area:6")
    await h.click("train:number:6")
    row = await session.current()
    await pick(f"ad:finish:{row['problem']}", "early-result",
               "Досрочно завершённая практика", "training-result")

    await h.message("/start")
    await h.click("nav:trainings")
    await h.click("train:areas")
    await h.click("train:area:6")
    await h.click("train:number:6")
    row = await answer_current()
    report.reset()
    with patch("app.bot.visual_delivery._render_png", side_effect=OSError("synthetic failure")):
        await h.click(f"ad:finish:{row['problem']}")
    await report.mark_text_fallback()

    await h.message("/start")
    await h.click("nav:trainings")
    await h.click("nav:mixed")
    mixed = MixedTrainingRepository(h.repository)
    for number in range(1, 20):
        state = await mixed.state(42)
        current = state["problem"]
        assert int(current["number"]) == number
        problem = current["problem_id"]
        if number == 6:
            await h.message(str(current["correct_answer"]))
            action = f"mixed:next:{problem}"
        else:
            action = f"mixed:skip:{problem}"
        if number == 19:
            await pick(action, "full-result", "Вся первая часть · итог", "training-result")
            assert (await mixed.state(42))["problem"]["number"] == 1
        else:
            await h.click(action)
    await h.click("nav:progress")
    assert await h.repository.user_state(42) == "progress"


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    if urlsplit(dsn).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use a disposable local PostgreSQL instance")
    repo = await open_storage(dsn, 790_000_000 + int(uuid4().hex[:8], 16))
    settings = config(
        oge_companion_adaptive_enabled=True, oge_visual_companion_only=True,
        oge_visual_user_ids="42", oge_visual_welcome_enabled=True, oge_visual_numbers_enabled=True,
        oge_visual_part2_enabled=True, oge_visual_stories_enabled=True,
        oge_visual_types_enabled=True,
        oge_visual_number_progress_enabled=True, oge_visual_training_result_enabled=True,
    )
    harness = Harness(repo, settings, ScenarioPostgresRepository(repo._pool))
    report = Evidence(harness)
    try:
        aggregate_examples(report)
        await exercise(harness, report)
        report.write()
    finally:
        await harness.bot.session.close()
        await repo._pool.close()
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(f'DROP SCHEMA "{repo.schema}" CASCADE')
        finally:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
