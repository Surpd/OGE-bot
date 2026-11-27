"""Capture actual optional cards through the companion dispatcher and local PostgreSQL."""

# Reuse the companion's existing synthetic transport and Bot API serializer.
# ruff: noqa: E402
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import asdict
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
from app.bot.result_cards import result_card
from app.bot.visual_cards import render_card
from app.bot.visual_models import (
    VisualBreakdown,
    VisualCard,
    VisualPractice,
)
from app.companion.storage import open_storage
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository
from scripts.live_training_acceptance import card, serialize

OUT = ROOT / "reports" / "visual-cards"
WIDTHS = (360, 390, 430)
REQUIRED_CASES = frozenset({
    "checkpoint", "checkpoint-finished", "long-checkpoint", "checkpoint-2", "long-result",
    "early-result", "mixed-result", "personal-result", "day-one-a", "day-one-b", "day-one-c",
    "no-practice-no-recommendation", "photo-checkpoint-fallback", "text-checkpoint",
    "text-checkpoint-finished", "text-fallback", "continue-transition", "stale-actions",
    "stale-after-continue",
})


def photo_media(payload: dict) -> dict:
    media = payload.get("media")
    if isinstance(media, str):
        media = json.loads(media)
    return media if isinstance(media, dict) else {}


def gallery_card(call: dict) -> str:
    """Preview actual photo caption placement, including editMessageMedia payloads."""
    attachments = call.get("attachments", {})
    if not attachments:
        return card(call)
    payload = call["payload"]
    media = photo_media(payload)
    caption = payload.get("caption") or media.get("caption") or ""
    parse_mode = payload.get("parse_mode") or media.get("parse_mode")
    contents = caption if parse_mode == "HTML" else escape(caption)
    caption_html = f'<div class="text">{contents}</div>' if contents else ""
    images = "".join(
        f'<img src="{escape(asset["path"])}" alt="Фото из payload Bot API">'
        for asset in attachments.values()
    )
    keyboard = "".join(
        '<div class="row">' + "".join(f'<span>{escape(button["text"])}</span>' for button in row)
        + '</div>' for row in (payload.get("reply_markup") or {}).get("inline_keyboard", ())
    )
    above = payload.get("show_caption_above_media") or media.get("show_caption_above_media")
    content = caption_html + images if above else images + caption_html
    return f'<article><small>{escape(call["method"])}</small>{content}{keyboard}</article>'


class Evidence:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.cursor = 0
        self.cases: list[dict] = []
        self.projections: list[VisualCard] = []
        self.projection_cursor = 0

    def reset(self) -> None:
        self.cursor = len(self.harness.transport.calls)
        self.projection_cursor = len(self.projections)

    def sizes(self, asset: str) -> dict[int, int]:
        with Image.open(OUT / asset) as image:
            assert image.width == 1200 and image.height <= 2700
            return {width: round(image.height * width / image.width) for width in WIDTHS}

    async def mark(
        self, name: str, label: str, expected_screen: str, *,
        message_id: int | None = None, issued: int | None = None, checkpoint: bool = False,
    ) -> dict:
        calls = self.harness.transport.calls[self.cursor:]
        projections = self.projections[self.projection_cursor:]
        self.reset()
        branded = []
        for method in calls:
            photo = method.photo if method.__api_method__ == "sendPhoto" else (
                method.media.media if method.__api_method__ == "editMessageMedia" else None
            )
            if getattr(photo, "filename", "") == f"bop-{expected_screen}.png":
                branded.append(method)
        assert len(branded) == 1, (name, [method.__api_method__ for method in calls])
        method = branded[0]
        actual_id = getattr(method, "message_id", None) or max(self.harness.transport.messages)
        if message_id is not None:
            assert actual_id == message_id, (name, actual_id, message_id)
            assert method.__api_method__ == "editMessageMedia"
            assert not any(m.__api_method__ == "sendPhoto" for m in calls)
        call = await serialize(self.harness.transport, self.harness.bot, branded[0], out=OUT)
        checks = {"actual_message_id": actual_id}
        visual = next((p for p in reversed(projections)
                       if p.screen.replace("_", "-") == expected_screen), None)
        if issued is not None:
            assert visual is not None and visual.breakdown is not None
            assert visual.breakdown.total == issued, (name, visual.breakdown, issued)
            assert visual.title == ("Результат тренировки" if checkpoint else
                                    "Тренировка завершена")
            labels = self.labels(call)
            if checkpoint:
                assert visual.subtitle.splitlines()[0] == "№6 · Вычисления"
                assert labels == ["Ещё 5 заданий →", "Завершить", "В меню"], labels
                assert self.copy(call) == "Хочешь продолжить?"
            else:
                assert labels[-3:] == ["К тренировкам", "Мой прогресс", "В меню"], labels
                assert "Хочешь продолжить?" not in self.copy(call)
            checks.update({"issued": issued, "checkpoint": checkpoint,
                           "inline_labels": labels, "caption": self.copy(call)})
        asset = next(iter(call["attachments"].values()))
        displayed = self.sizes(asset["path"])
        item = {
            "name": name, "label": label, "call": call, "displayed_heights": displayed,
            "checks": checks,
        }
        if visual is not None:
            item["projection"] = asdict(visual)
        self.cases.append(item)
        print(name, displayed, flush=True)
        return item

    @staticmethod
    def labels(call: dict) -> list[str]:
        return [button["text"] for row in call["payload"].get("reply_markup", {}).get(
            "inline_keyboard", (),
        ) for button in row]

    @staticmethod
    def copy(call: dict) -> str:
        payload = call["payload"]
        return payload.get("text") or payload.get("caption") or photo_media(payload).get(
            "caption", "",
        )

    async def transition(
        self, name: str, label: str, *, message_id: int, allowed: set[str],
        source: dict | None = None, expected_issued: int | None = None,
    ) -> dict:
        calls = self.harness.transport.calls[self.cursor:]
        self.reset()
        changes = [m for m in calls if m.__api_method__ != "answerCallbackQuery"]
        assert changes and all(m.__api_method__ in allowed for m in changes), (
            name, [m.__api_method__ for m in changes],
        )
        assert all(getattr(m, "message_id", None) == message_id for m in changes)
        serialized = [await serialize(self.harness.transport, self.harness.bot, m, out=OUT)
                      for m in changes]
        final = serialized[-1]
        if expected_issued is not None:
            assert f"из {expected_issued}" in self.copy(final)
            assert "Тренировка завершена" in self.copy(final)
            assert self.labels(final)[-3:] == ["К тренировкам", "Мой прогресс", "В меню"]
            assert "Хочешь продолжить?" not in self.copy(final)
        item = {
            "name": name, "label": label, "call": final, "transition_calls": serialized,
            "checks": {"same_message_id": message_id, "no_sendPhoto": True,
                       "issued": expected_issued}, "displayed_heights": {},
        }
        if source is not None:
            item["previous_card"] = source["name"]
        self.cases.append(item)
        return item

    async def continued(self, message_id: int, prompt_id: int) -> None:
        calls = self.harness.transport.calls[self.cursor:]
        self.reset()
        clear = [m for m in calls if m.__api_method__ == "editMessageReplyMarkup"
                 and m.message_id == message_id]
        assert len(clear) == 1 and clear[0].reply_markup is None
        delivery = [m for m in calls if m.__api_method__ in {
            "sendMessage", "sendRichMessage", "sendPhoto",
        }]
        assert delivery and calls.index(clear[0]) < calls.index(delivery[0])
        assert self.harness.transport.messages[message_id].reply_markup is None
        assert prompt_id != message_id and prompt_id in self.harness.transport.messages
        call = await serialize(self.harness.transport, self.harness.bot, clear[0], out=OUT)
        self.cases.append({
            "name": "continue-transition", "label": "Продолжение убирает прежние кнопки",
            "call": call, "displayed_heights": {},
            "checks": {"old_message_id": message_id, "new_prompt_id": prompt_id,
                       "old_keyboard_removed": True},
        })

    async def stale(
        self, saved: list[tuple], session: Session, *, name: str = "stale-actions",
    ) -> None:
        before = await session.current()
        self.reset()
        for entry in saved:
            await self.harness.click(saved=entry)
        assert await session.current() == before
        calls = self.harness.transport.calls[self.cursor:]
        assert calls and all(m.__api_method__ == "answerCallbackQuery" for m in calls)
        self.reset()
        self.cases.append({
            "name": name, "label": "Старые и повторные нажатия отклонены",
            "source": "Реальные callback updates после завершения сессии.",
            "checks": {"callbacks": len(saved), "only_acknowledgements": True,
                       "unchanged_session": True}, "displayed_heights": {},
        })

    def aggregate(self, name: str, label: str, visual: VisualCard, *, origin: str) -> None:
        png = render_card(visual)
        digest = hashlib.sha256(png).hexdigest()
        asset = f"assets/{digest}.png"
        (OUT / asset).parent.mkdir(parents=True, exist_ok=True)
        (OUT / asset).write_bytes(png)
        self.cases.append({
            "name": name, "label": label, "asset": asset, "source": origin,
            "displayed_heights": self.sizes(asset),
            "projection": asdict(visual),
        })

    async def mark_text_fallback(
        self, name: str = "text-fallback", *, checkpoint: bool = False, issued: int = 1,
    ) -> dict:
        calls = self.harness.transport.calls[self.cursor:]
        self.reset()
        text_calls = [method for method in calls if method.__api_method__ == "sendMessage"]
        assert len(text_calls) == 1 and not any(
            method.__api_method__ == "sendPhoto" for method in calls
        )
        call = await serialize(self.harness.transport, self.harness.bot, text_calls[0], out=OUT)
        text = call["payload"]["text"]
        assert "Решено верно" in text and f"из {issued}" in text
        assert ("Результат тренировки" if checkpoint else "Тренировка завершена") in text
        if checkpoint:
            assert self.labels(call) == ["Ещё 5 заданий →", "Завершить", "В меню"]
        item = {
            "name": name, "label": "Текстовый резерв при отказе рендера",
            "call": call, "displayed_heights": {},
            "checks": {"issued": issued, "checkpoint": checkpoint, "no_sendPhoto": True,
                       "actual_message_id": max(self.harness.transport.messages)},
        }
        self.cases.append(item)
        return item

    def write(self) -> None:
        names = [item["name"] for item in self.cases]
        assert len(names) == len(set(names)), "Duplicate acceptance case"
        assert REQUIRED_CASES <= set(names), "Incomplete acceptance"
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
                    f'{gallery_card(item["call"])}'
                )
            else:
                body = f'<p>{escape(item["source"])}</p>'
                if "asset" in item:
                    body += f'<img src="{item["asset"]}" alt="{escape(item["label"])}">'
            if item.get("checks"):
                body += f'<pre>{escape(json.dumps(item["checks"], ensure_ascii=False))}</pre>'
            sections.append(
                f'<section id="{name}"><h2>{escape(item["label"])}</h2>{body}</section>'
            )
        (OUT / "manifest.json").write_text(
            json.dumps([
                {key: value for key, value in item.items()
                 if key not in {"call", "transition_calls"}} for item in self.cases
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
            'article>small{display:block;margin:6px 12px}.text{white-space:pre-wrap;'
            'margin:8px 12px}article .text:empty{display:none}pre{white-space:pre-wrap;'
            'overflow-wrap:anywhere;margin:8px 12px;font-size:11px}'
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
        return result_card(
            title, outcomes.total, outcomes.independent + outcomes.assisted,
            outcomes.independent, outcomes.skipped, subtitle=subtitle,
            practice=practice, recommendation=review,
        )

    checkpoint = "Результат тренировки"
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
    empty_optional = result(finish, VisualBreakdown(1, 0, 1, 0), subtitle="№6 · Вычисления")
    assert not empty_optional.practice and not empty_optional.sections
    report.aggregate(
        "no-practice-no-recommendation", "Без закрепления и рекомендации", empty_optional,
        origin="Синтетические итоги без данных для необязательных секций.",
    )


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
        assert row is not None
        answer = str(problem_data(row)["correct_answer"])
        await h.message(answer)
        return row

    async def open_number():
        await h.message("/start")
        await h.click("nav:trainings")
        await h.click("train:areas")
        await h.click("train:area:6")
        await h.click("train:number:6")

    async def block():
        for index in range(5):
            if index == 4:
                report.reset()
            row = await answer_current()
            if index < 4:
                await h.click(f"ad:next:{row['problem']}")
        return row

    # Finish directly on the first checkpoint: same message, final controls, no duplicate photo.
    await h.click("train:number:6")
    row = await block()
    await report.mark(
        "checkpoint", "Первые пять · действующие подпись и кнопки", "training-result",
        issued=5, checkpoint=True,
    )
    first_finish = h.button(f"ad:finish:{row['problem']}")
    first_continue = h.button(f"ad:continue:{row['problem']}")
    report.reset()
    await h.click(saved=first_finish)
    await report.mark(
        "checkpoint-finished", "Завершение первых пяти в том же сообщении", "training-result",
        message_id=first_finish[0].message_id, issued=5,
    )
    assert await session.current() is None

    # Separate long session: Continue clears old controls and adds exactly five slots.
    await open_number()
    row = await block()
    await report.mark(
        "long-checkpoint", "Длинная практика · первые пять", "training-result",
        issued=5, checkpoint=True,
    )
    old_continue = h.button(f"ad:continue:{row['problem']}")
    old_finish = h.button(f"ad:finish:{row['problem']}")
    report.reset()
    await h.click(saved=old_continue)
    current = await session.current()
    assert current is not None and current["position"] == 5
    await report.continued(old_continue[0].message_id, current["prompt"])
    await report.stale([old_continue, old_finish], session, name="stale-after-continue")
    row = await block()
    second = await report.mark(
        "checkpoint-2", "Длинная практика · второй блок из пяти", "training-result",
        issued=5, checkpoint=True,
    )
    assert second["checks"]["actual_message_id"] != old_continue[0].message_id
    assert "Задания 6–10" in second["projection"]["subtitle"]
    second_finish = h.button(f"ad:finish:{row['problem']}")
    report.reset()
    await h.click(saved=second_finish)
    await report.mark(
        "long-result", "Длинная практика · суммарные десять в том же сообщении", "training-result",
        message_id=second_finish[0].message_id, issued=10,
    )
    assert await session.current() is None
    await report.stale(
        [first_finish, first_continue, old_continue, old_finish, second_finish, second_finish],
        session,
    )

    await h.message("/start")
    await h.click("nav:progress")
    await h.click("progress:details")
    await pick("progress:number:6", "number-progress", "Прогресс по №6", "number-progress")

    for strategy, label in (("mixed", "Смешанная"), ("personal", "Персональная")):
        await h.message("/start")
        await h.click("nav:trainings")
        await h.click(f"train:{strategy}")
        await block()
        await report.mark(
            f"{strategy}-result", f"{label} тренировка · автоматический итог пяти",
            "training-result", issued=5,
        )
        assert await session.current() is None

    await open_number()
    for _ in range(2):
        row = await answer_current()
        await h.click(f"ad:next:{row['problem']}")
    row = await session.current()
    assert row is not None and row["position"] == 2 and row["outcome"] == "issued"
    report.reset()
    await h.click(f"ad:finish:{row['problem']}")
    early = await report.mark(
        "early-result", "Досрочный итог учитывает два ответа и выданное третье задание",
        "training-result", issued=3,
    )
    breakdown = early["projection"]["breakdown"]
    assert breakdown["independent"] + breakdown["assisted"] == 2

    # A photo checkpoint must also become final in place when the renderer fails.
    await open_number()
    row = await block()
    source = await report.mark(
        "fallback-checkpoint-source", "Фото до отказа рендера", "training-result",
        issued=5, checkpoint=True,
    )
    finish = h.button(f"ad:finish:{row['problem']}")
    report.reset()
    with patch("app.bot.visual_delivery._render_png", side_effect=OSError("synthetic failure")):
        await h.click(saved=finish)
    await report.transition(
        "photo-checkpoint-fallback", "Отказ рендера · финал в том же фото",
        message_id=finish[0].message_id, allowed={"editMessageCaption", "editMessageMedia"},
        source=source, expected_issued=5,
    )

    # Renderer failures on both the checkpoint and its Finish use one text message.
    await open_number()
    with patch("app.bot.visual_delivery._render_png", side_effect=OSError("synthetic failure")):
        row = await block()
        await report.mark_text_fallback("text-checkpoint", checkpoint=True, issued=5)
        text_finish = h.button(f"ad:finish:{row['problem']}")
        report.reset()
        await h.click(saved=text_finish)
    await report.transition(
        "text-checkpoint-finished", "Текстовый промежуточный итог заменён финалом",
        message_id=text_finish[0].message_id, allowed={"editMessageText"}, expected_issued=5,
    )

    # A mid-block result still has its ordinary sendMessage fallback.
    await open_number()
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
        oge_visual_stories_enabled=True,
        oge_visual_types_enabled=True,
        oge_visual_number_progress_enabled=True, oge_visual_training_result_enabled=True,
    )
    harness = Harness(repo, settings, ScenarioPostgresRepository(repo._pool))
    report = Evidence(harness)

    from app.bot.visual_delivery import _card_png

    def capture_render(visual: VisualCard) -> bytes:
        report.projections.append(visual)
        return _card_png(visual)

    try:
        aggregate_examples(report)
        with patch("app.bot.visual_delivery._card_png", side_effect=capture_render):
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
