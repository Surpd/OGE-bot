"""Publish synthetic dispatcher payloads for the training menu and practice flow."""

# Imports follow workspace path setup.
# ruff: noqa: E402
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import asyncpg
from aiogram import Bot
from aiogram.methods.base import TelegramMethod
from aiogram.types import InputFile
from test_companion_qa import Harness, config
from test_inline_dispatcher_postgres import TelegramSession

from app.adaptive.session import Session
from app.bot.adaptive import problem_data
from app.companion.storage import open_storage
from app.math.scenarios.recent_questions import _FINITE_FAMILY_SEEDS
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository

OUT = ROOT / "reports" / "live-training-acceptance"
FLOOR = "STOVE-F04-FLOOR-AREA"
SMALL_POOL = "PAPER-F07"
VISIBLE = {"sendMessage", "sendRichMessage", "sendPhoto", "editMessageText", "editMessageCaption"}


async def serialize(transport: TelegramSession, bot: Bot, method: TelegramMethod) -> dict:
    """Apply aiogram's own request encoding and archive actual uploaded bytes."""
    files: dict[str, InputFile] = {}
    payload = {
        name: prepared
        for name, value in method.model_dump(warnings=False).items()
        if (prepared := transport.prepare_value(value, bot=bot, files=files)) is not None
    }
    for name in ("reply_markup", "rich_message", "reply_parameters"):
        if isinstance(payload.get(name), str):
            payload[name] = json.loads(payload[name])
    assets = {}
    for identifier, file in files.items():
        data = b"".join([chunk async for chunk in file.read(bot)])
        digest = hashlib.sha256(data).hexdigest()
        relative = f"assets/{digest}.png"
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), "unexpected upload format"
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        assets[identifier] = {"path": relative, "filename": file.filename, "sha256": digest}
    result = {"method": method.__api_method__, "payload": payload}
    if assets:
        result["attachments"] = assets
    return result


class Report:
    def __init__(self, harness: Harness) -> None:
        self.h = harness
        self.cursor = len(harness.transport.calls)
        self.cards: dict[str, tuple[str, list[dict]]] = {}

    async def mark(self, case: str, label: str) -> None:
        calls = self.h.transport.calls[self.cursor:]
        self.cursor = len(self.h.transport.calls)
        serialized = [await serialize(self.h.transport, self.h.bot, method) for method in calls]
        assert any(call["method"] in VISIBLE for call in serialized), (case, serialized)
        self.cards[case] = label, serialized

    def write(self) -> None:
        payload_dir = OUT / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        sections = []
        for case, (label, calls) in self.cards.items():
            (payload_dir / f"{case}.json").write_text(
                json.dumps({"case": case, "label": label, "calls": calls}, ensure_ascii=False,
                           indent=2) + "\n",
                encoding="utf-8",
            )
            cards = "".join(card(call) for call in calls if call["method"] in VISIBLE)
            sections.append(
                f'<section id="{case}"><h2>{html.escape(label)}</h2>'
                f'<a href="payloads/{case}.json">Фактический payload Bot API</a>{cards}</section>'
            )
        gallery = (
            '<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>bop Math · приёмка тренировок</title>'
            '<style>'
            '*{box-sizing:border-box}body{margin:0;color:#142837;background:#e9eff2;'
            'font:15px/1.45 system-ui,sans-serif}main{max-width:600px;margin:auto;padding:12px}'
            'header{padding:16px 14px;border-radius:12px;background:#10384a;color:white}'
            'h1{font-size:23px;margin:0}h2{font-size:17px;margin:0 0 3px}header p{margin:7px 0 0}'
            'section{margin:14px 0;padding:12px;background:white;border-radius:12px}'
            'a{color:#18597a;font-size:13px}article{margin-top:9px;padding:10px;background:#f0f6f7;'
            'border-radius:10px;overflow-wrap:anywhere}article p{margin:0 0 8px}'
            '.text{white-space:pre-wrap}small{display:block;color:#446477;margin-bottom:6px}'
            '.row{display:flex;gap:4px;margin-top:5px}'
            '.row span{flex:1;min-width:0;text-align:center;'
            'padding:5px;background:#dbe8ef;border-radius:5px;font-size:12px}'
            'img{width:100%;height:auto;border-radius:7px;display:block;margin:8px 0}'
            '</style><main><header><h1>bop Math · приёмка тренировок</h1>'
            '<p>Офлайн-превью payload с синтетическим учеником. Снимки галереи сделаны в Chromium.'
            '</p></header>' + "".join(sections) + '</main></html>'
        )
        (OUT / "index.html").write_text(gallery, encoding="utf-8")


def card(call: dict) -> str:
    payload = call["payload"]
    uploads = dict(call.get("attachments", {}))
    if "rich_message" in payload:
        rich = payload["rich_message"]
        contents = rich.get("html") or ""
        for media in rich.get("media", ()):
            item = media["media"]["media"]
            asset = uploads.pop(item.removeprefix("attach://"), None)
            if asset:
                contents = contents.replace(f'tg://photo?id={media["id"]}', asset["path"])
    elif payload.get("parse_mode") == "HTML":
        contents = f'<div class="text">{payload.get("text") or payload.get("caption") or ""}</div>'
    else:
        contents = '<div class="text">' + html.escape(
            payload.get("text") or payload.get("caption") or ""
        ) + "</div>"
    images = "".join(
        f'<img src="{asset["path"]}" alt="Материал из payload Bot API">'
        for asset in uploads.values()
    )
    markup = payload.get("reply_markup") or {}
    keyboard = "".join(
        '<div class="row">' + "".join(
            f'<span>{html.escape(button["text"])}</span>' for button in row
        ) + "</div>"
        for row in markup.get("inline_keyboard", ())
    )
    return f'<article><small>{call["method"]}</small>{contents}{images}{keyboard}</article>'


async def access_family(h: Harness, number: int, family: str) -> None:
    await h.click(f"train:area:{number}")
    for page in range(1, 8):
        try:
            h.button(f"train:family:{family}")
        except AssertionError:
            await h.click(f"train:area:{number}:{page}")
        else:
            return
    raise AssertionError(f"Family unavailable: {family}")


async def run_with_synthetic_user(exercise_flow) -> None:
    dsn = os.environ["DATABASE_URL"]
    if urlsplit(dsn).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use a disposable local PostgreSQL instance")
    repo = await open_storage(dsn, 780_000_000 + int(uuid4().hex[:8], 16))
    harness = Harness(
        repo, config(oge_companion_adaptive_enabled=True), ScenarioPostgresRepository(repo._pool),
    )
    try:
        await harness.message("/start")
        await harness.click("exit")
        await exercise_flow(harness)
    finally:
        await harness.bot.session.close()
        await repo._pool.close()
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(f'DROP SCHEMA "{repo.schema}" CASCADE')
        finally:
            await conn.close()


async def exercise(h: Harness) -> None:
    report = Report(h)
    session = Session(h.repository, 42)
    await h.click("nav:trainings")
    await report.mark("hub", "Четыре направления тренировок")
    await h.click("train:areas")
    await report.mark("numbers", "Единый выбор номера")
    await h.click("nav:linked")
    await report.mark("linked-picker", "Выбор связанного сюжета №1–5")
    await h.click("oge15:linked:STOVE")
    await report.mark("linked-stove", "Печи · общий сюжет и первый вопрос")
    await h.message("/start")
    await h.click("nav:trainings")
    await h.click("train:areas")
    report.cursor = len(h.transport.calls)
    await access_family(h, 3, FLOOR)
    await report.mark("family-picker", "Выбор математического типа №3")
    await h.click(f"train:family:{FLOOR}")
    seen = set()
    for position in range(5):
        active = await session.current()
        assert active["position"] == position
        data = problem_data(active)
        assert data["family_id"] == FLOOR and data["fingerprint"] not in seen
        seen.add(data["fingerprint"])
        await report.mark(f"floor-{position + 1}", f"Площадь пола · вариант {position + 1}")
        if position == 0:
            await h.click(f"ad:data:{active['problem']}")
            await report.mark("floor-data", "Площадь пола · схема и полный каталог печей")
        await h.message(str(data["correct_answer"]))
        if position < 4:
            report.cursor = len(h.transport.calls)
            await h.click(f"ad:next:{active['problem']}")
    await report.mark("checkpoint", "Промежуточный итог после пяти задач")
    await h.click(f"ad:continue:{active['problem']}")
    active = await session.current()
    assert active["position"] == 5 and problem_data(active)["family_id"] == FLOOR
    await report.mark("continue-practice", "Продолжение практики на шестой задаче")
    await h.click(f"ad:finish:{active['problem']}")
    assert await session.current() is None
    await report.mark("finish-early", "Досрочное завершение и накопительный итог")

    for action, label in (
        ("personal", "Персональная тренировка"),
        ("mixed", "Смешанная тренировка"),
    ):
        await h.message("/start")
        await h.click("nav:trainings")
        report.cursor = len(h.transport.calls)
        await h.click(f"train:{action}")
        await report.mark(action, label)
        active = await session.current()
        assert active["strategy"] == action
        await h.click(f"ad:finish:{active['problem']}")

    await h.message("/start")
    await h.click("nav:trainings")
    await h.click("train:areas")
    await access_family(h, 5, SMALL_POOL)
    await h.click(f"train:family:{SMALL_POOL}")
    capacity = len(_FINITE_FAMILY_SEEDS[SMALL_POOL])
    for position in range(capacity):
        active = await session.current()
        assert active["position"] == position and problem_data(active)["family_id"] == SMALL_POOL
        await h.message(str(problem_data(active)["correct_answer"]))
        report.cursor = len(h.transport.calls)
        advance = "continue" if (position + 1) % 5 == 0 else "next"
        await h.click(f"ad:{advance}:{active['problem']}")
    active = await session.current()
    token = f"{active['id']}.{active['position']}"
    assert active["position"] == capacity and active["problem"] is None
    h.button(f"ad:repeat:{token}")
    await report.mark("exhausted", f"Исчерпаны все {capacity} вариантов {SMALL_POOL}")
    await h.click(f"ad:repeat:{token}")
    active = await session.current()
    assert active["problem"] is not None and active["position"] == capacity
    await report.mark("repeat", "Осознанный повтор варианта")
    await h.message(str(problem_data(active)["correct_answer"]))
    totals = await session.totals(active["id"])
    assert (totals["solved"], totals["independent"]) == (capacity + 1, capacity)
    await h.click(f"ad:finish:{active['problem']}")

    await h.message("/start")
    await h.click("nav:trainings")
    report.cursor = len(h.transport.calls)
    await h.click("nav:mixed")
    mixed = MixedTrainingRepository(h.repository)
    first = (await mixed.state(42))["problem"]
    assert first["number"] == 1
    await report.mark("full-part-one", "Первая часть целиком · начало связанного сюжета")
    for number in range(1, 6):
        problem = (await mixed.state(42))["problem"]
        assert problem["number"] == number
        assert problem["scenario_snapshot"] == first["scenario_snapshot"]
        await h.click(f"mixed:skip:{problem['problem_id']}")
    for number in range(6, 20):
        problem = (await mixed.state(42))["problem"]
        assert problem["number"] == number
        await h.click(f"mixed:skip:{problem['problem_id']}")
    assert (await mixed.state(42))["problem"]["number"] == 1
    report.write()


if __name__ == "__main__":
    asyncio.run(run_with_synthetic_user(exercise))
