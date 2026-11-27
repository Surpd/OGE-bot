"""Generate a local progress gallery from the real dispatcher and fixture-only PostgreSQL."""

# Imports follow workspace path setup.
# ruff: noqa: E402
import asyncio
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
from test_progress_visual_route import ProgressRoute, actions, photo_filename, seed_progress

from app.bot import visual_delivery
from app.companion.storage import open_storage
from scripts.live_training_acceptance import serialize

OUTPUT = ROOT / "reports" / "progress-route"
WIDTHS = (360, 390, 430)
DESKTOP = (500, 440)
PREVIEW_CASES = {
    "numbers", "number-dense", "types-dense", "journal-long", "journal-empty", "number-empty",
}


class Gallery:
    def __init__(self, route):
        self.route = route
        self.cases = []
        self.cards = []
        self.render = visual_delivery._card_png

    def capture_render(self, card):
        self.cards.append(card)
        return self.render(card)

    async def pick(self, action, key, title, screen, *, same_id=False):
        previous = self.route.current.message_id
        methods = len(self.route.transport.calls)
        projections = len(self.cards)
        sent = await self.route.click(action)
        produced = self.route.transport.calls[methods:]
        filename = f"bop-{screen.replace('_', '-')}.png"
        (method,) = [m for m in produced if photo_filename(m) == filename]
        (card,) = [item for item in self.cards[projections:] if item.screen == screen]
        if same_id:
            assert previous == sent.message_id == method.message_id
            assert method.__api_method__ == "editMessageMedia"
        call = await serialize(self.route.transport, self.route.bot, method, out=OUTPUT)
        asset = next(iter(call["attachments"].values()))["path"]
        with Image.open(OUTPUT / asset) as raw:
            width, height = raw.size
        desktop_scale = min(DESKTOP[0] / width, DESKTOP[1] / height)
        record = {
            "key": key, "title": title, "projection": asdict(card), "bot_api": call, "asset": asset,
            "raw_size": [width, height],
            "mobile_heights": {w: round(w * height / width) for w in WIDTHS},
            "desktop_fit": [round(width * desktop_scale), round(height * desktop_scale)],
            "message_id": sent.message_id,
            "overview_id": (
                sent.reply_to_message.message_id if sent.reply_to_message is not None else None
            ),
        }
        self.cases.append(record)
        print(f"{key}: {width}x{height} → {record['mobile_heights']}", flush=True)
        return sent

    def write(self):
        (OUTPUT / "payloads").mkdir(parents=True, exist_ok=True)
        for item in self.cases:
            (OUTPUT / "payloads" / f"{item['key']}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
        sections = "".join(case_html(item) for item in self.cases)
        phone_views = " ".join(f'<a href="{width}.html">{width} px</a>' for width in WIDTHS)
        overview = page(
            "Прогресс bop Math",
            '<header><h1>Прогресс bop Math</h1>'
            '<p>Фактические PNG и кнопки из тестовых ответов Telegram Bot API. '
            'Данные созданы для проверки в изолированной PostgreSQL.</p>'
            f'<nav>Скриншоты и карточки: {phone_views}</nav></header>{sections}',
        )
        (OUTPUT / "index.html").write_text(overview, encoding="utf-8")
        for width in WIDTHS:
            selected = [item for item in self.cases if item["key"] in PREVIEW_CASES]
            cards = "".join(
                f'<section class="capture"><h2>{escape(item["title"])}</h2>'
                f'{preview_html(item, width)}</section>' for item in selected
            )
            content = (
                f'<main class="mobile" style="--preview-width:{width}px">'
                f'<header><h1>{width} px</h1><a href="index.html">Вся галерея</a> · '
                f'<a href="screenshots/{width}.png">PNG</a></header>{cards}</main>'
            )
            (OUTPUT / f"{width}.html").write_text(page(f"Прогресс · {width} px", content),
                                                       encoding="utf-8")


def preview_html(item, width):
    markup = item["bot_api"]["payload"]["reply_markup"]["inline_keyboard"]
    keyboard = "".join(
        '<div class="keys">' + "".join(
            f'<span title="{escape(button["callback_data"].partition("~")[0])}">'
            f'{escape(button["text"])}</span>' for button in row
        ) + "</div>" for row in markup
    )
    key = escape(item["key"])
    label = f"{width} px" if isinstance(width, int) else "Вписывание в 500 × 440 px"
    size = f"width:{width}px" if isinstance(width, int) else "width:500px"
    photo_style = (
        f'width:{item["desktop_fit"][0]}px' if not isinstance(width, int) else "width:100%"
    )
    return (
        f'<figure id="{key}-{width}" style="{size}"><figcaption>{label}</figcaption>'
        f'<img style="{photo_style}" src="{escape(item["asset"])}" '
        f'alt="{escape(item["title"])}">{keyboard}</figure>'
    )


def case_html(item):
    key = escape(item["key"])
    raw_width, raw_height = item["raw_size"]
    desktop_width, desktop_height = item["desktop_fit"]
    lengths = " · ".join(f"{w} × {h}" for w, h in item["mobile_heights"].items())
    desktop = ""
    if desktop_width < DESKTOP[0]:
        desktop = (
            f'<details><summary>Фото в пределах 500 × 440 px: {desktop_width} × {desktop_height}'
            f'</summary>{preview_html(item, "desktop")}</details>'
        )
    return (
        f'<section id="{key}"><h2>{escape(item["title"])}</h2>'
        f'<p>Исходный PNG {raw_width} × {raw_height} · размеры фото в чате {lengths}</p>'
        f'<a href="payloads/{key}.json">Payload Bot API и данные</a>'
        f'<div class="views">{"".join(preview_html(item, width) for width in WIDTHS)}</div>'
        f'{desktop}</section>'
    )


def page(title, content):
    return f'''<!doctype html>
<html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#e9eff2;color:#152a2b;
font:15px/1.4 Arial,sans-serif}}body>header,body>section{{max-width:1220px;margin:14px auto;
padding:12px;background:#f8faf9;border-radius:10px}}h1,h2,p{{margin:0 0 8px}}h2{{font-size:18px}}
a{{color:#205d6a}}nav a{{margin-right:10px}}.views{{display:flex;gap:12px;align-items:flex-start;
overflow:auto;padding:6px 0 12px}}figure{{margin:0;max-width:100%;flex:none}}
img{{display:block;height:auto;margin:0 auto;border-radius:10px}}figcaption{{font-size:13px;
padding:6px 2px;color:#435753}}.keys{{display:flex;gap:4px;margin:4px 0}}.keys span{{flex:1;
min-width:0;text-align:center;padding:7px 4px;min-height:31px;color:#25454a;background:#dce8ea;
border-radius:6px;font-size:13px;overflow-wrap:anywhere}}summary{{cursor:pointer;color:#205d6a}}
.mobile{{width:var(--preview-width);margin:0 auto}}.mobile header{{padding:12px 8px}}
.capture{{margin:6px 0 22px}}.capture h2{{margin:0;padding:6px 8px;font-size:15px}}
.capture figcaption{{display:none}}.capture img{{border-radius:7px}}
</style>{content}</html>'''


async def exercise(gallery):
    route = gallery.route
    await route.start()
    pick = gallery.pick
    await pick("progress:details", "numbers", "Подробнее по номерам", "progress_numbers")
    await pick("progress:number:6", "number-normal", "№6 · прогресс", "number_progress",
               same_id=True)
    await pick("progress:family:6:0", "types", "№6 · все типы", "number_progress", same_id=True)
    await route.click("progress:number:6")
    await route.click("progress:details")
    await pick("progress:number:13", "number-dense", "№13 · заполненный прогресс",
               "number_progress", same_id=True)
    await pick("progress:family:13:0", "types-dense", "№13 · типы с длинными названиями",
               "number_progress", same_id=True)
    await route.click("progress:number:13")
    await pick("progress:numhist:13:0", "journal-long", "История №13 · длинные названия",
               "progress_journal", same_id=True)
    await pick("progress:filter:ad.0", "journal-filter", "Журнал · выбор номера",
               "progress_numbers", same_id=True)
    await pick("progress:numhist:7:0", "journal-empty", "История №7 · пустой список",
               "progress_journal", same_id=True)
    await pick("progress:number:7", "number-empty", "№7 · задач пока нет", "number_progress",
               same_id=True)
    await route.click("progress:summary")
    await pick("progress:history:0", "journal-all", "История · все задания", "progress_journal")
    await pick("progress:errors:0", "journal-errors", "Журнал · с ошибками", "progress_journal",
               same_id=True)
    selected = await pick("progress:errors:4", "journal-page-two", "Ошибки · страница 2",
                          "progress_journal", same_id=True)
    (first_record, *_) = actions(selected, "progress:item:")
    await route.click(first_record)
    await pick("progress:return:e4", "journal-return", "Возврат на страницу 2 ошибок",
               "progress_journal")


async def main():
    dsn = os.environ["DATABASE_URL"]
    if urlsplit(dsn).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use a disposable PostgreSQL instance on loopback")
    repository = await open_storage(dsn, 810_000_000 + int(uuid4().hex[:8], 16))
    route = ProgressRoute(repository)
    gallery = Gallery(route)
    try:
        await seed_progress(repository)
        with patch.object(visual_delivery, "_card_png", side_effect=gallery.capture_render):
            await exercise(gallery)
        gallery.write()
    finally:
        await route.bot.session.close()
        await repository._pool.close()
        connection = await asyncpg.connect(dsn)
        try:
            await connection.execute(f'DROP SCHEMA "{repository.schema}" CASCADE')
        finally:
            await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
