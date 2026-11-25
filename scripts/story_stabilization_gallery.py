"""Render deterministic, offline previews of outgoing OGE Telegram payloads."""

# E402 is needed because this standalone script adds the checkout to sys.path;
# E501 is needed for a few embedded HTML/CSS template lines.
# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import asyncio
import csv
import html
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import BufferedInputFile, Chat, Message, PhotoSize, User

from app.bot import mixed_training
from app.bot.math_layout import question_message, solution_message
from app.bot.presentation import (
    hint_message,
    send_text,
)
from app.bot.scenario_training import public_registry, render_session
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.persistence.scenario_repository import ScenarioPostgresRepository, ScenarioSession

STORIES = ("TYRES", "PAPER", "STOVE", "TARIFF", "GARDEN", "FLAT")
WIDTHS = (360, 390, 430)
OUT = Path(
    r"C:\Users\mitya\.codex\visualizations\2026\11\25\01a21309-32d3-7d51-8b7c-434987d3435b\oge-story-gallery"
)


class OfflineCaptureSession(BaseSession):
    """BaseSession transport that records Bot API methods without network access."""

    def __init__(self, case_id: str) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []
        self.message_id = 0
        self.case_id = case_id

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: object, **kwargs: object):
        if False:
            yield b""

    async def make_request(  # noqa: ASYNC109 (aiogram BaseSession interface)
        self, bot: Bot, method: object, timeout: int | None = None  # noqa: ASYNC109
    ):
        self.message_id += 1
        name = getattr(method, "__api_method__", type(method).__name__)
        record: dict[str, object] = {"method": name, "message_id": self.message_id}
        for field in ("text", "caption", "parse_mode", "reply_markup", "rich_message"):
            value = getattr(method, field, None)
            if value is not None:
                record[field] = (
                    value.model_dump(mode="json", exclude_none=True)
                    if hasattr(value, "model_dump")
                    else str(value)
                )
        photo = getattr(method, "photo", None)
        if isinstance(photo, BufferedInputFile):
            target_name = f"{self.case_id}-api-{self.message_id}.png"
            target = OUT / "media" / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(photo.data)
            record["filename"] = target_name
            record["photo_bytes"] = len(photo.data)
        self.calls.append(record)
        return Message(
            message_id=self.message_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=123456, is_bot=True, first_name="Offline gallery"),
            photo=[
                PhotoSize(
                    file_id=f"offline-{self.message_id}",
                    file_unique_id="offline",
                    width=1,
                    height=1,
                )
            ]
            if name == "sendPhoto"
            else None,
        ).as_(bot)


class OfflineRepository:
    async def math_display(self, user_id: int | None, template_id: str | None = None) -> str:
        return "rich"

    async def claim_navigation_message(self, *args: object, **kwargs: object) -> bool:
        return False


async def capture_scenario_session(snapshot: object, position: int, case_id: str) -> list[dict[str, object]]:
    """Run scenario_training.render_session through the actual presentation transport."""
    session = OfflineCaptureSession(case_id)
    bot = Bot("123456:OFFLINE", session=session)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Synthetic student"),
    ).as_(bot)
    repo = OfflineRepository()
    store = AsyncMock(spec=ScenarioPostgresRepository)
    store.close_legacy_with_exposed_answer.return_value = False
    scenario_session = ScenarioSession(
        uuid4(), uuid4(), PracticeMode.FULL, "active", position, 0, "active", 0, 0,
        None, None, snapshot,
    )
    await render_session(
        message, store, scenario_session, show_assets=True, user_id_override=42,
        repository=repo,
    )
    result = list(session.calls)
    await bot.session.close()
    return result


async def capture_presentation_message(body: object, case_id: str) -> list[dict[str, object]]:
    session = OfflineCaptureSession(case_id)
    bot = Bot("123456:OFFLINE", session=session)
    message = Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Synthetic student"),
    ).as_(bot)
    await send_text(message, OfflineRepository(), body)
    result = list(session.calls)
    await bot.session.close()
    return result


async def capture_mixed_problem(snapshot: object, position: int, case_id: str) -> list[dict[str, object]]:
    """Run mixed_training._send_problem through the real presentation and BaseSession path."""
    session = OfflineCaptureSession(case_id)
    bot = Bot("123456:OFFLINE", session=session)
    message = Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Synthetic student"),
    ).as_(bot)
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
    problem["number"] = position
    store = AsyncMock()
    store.set_prompt.return_value = True
    await mixed_training._send_problem(
        message, OfflineRepository(), store, problem, user_id=42,
    )
    result = list(session.calls)
    await bot.session.close()
    return result


def api_message_card(call: dict[str, object], case_id: str, width: int) -> str:
    method = str(call["method"])
    label = f"{method} · {case_id} · {width}px"
    rich = call.get("rich_message")
    if isinstance(rich, dict) and isinstance(rich.get("html"), str):
        content = str(rich["html"])
    else:
        content = str(call.get("text") or call.get("caption") or "")
    escaped_payload = html.escape(json.dumps(call, ensure_ascii=False, indent=2))
    asset = call.get("filename")
    if method == "sendPhoto" and isinstance(asset, str):
        media = (f'<div class="bubble media"><img src="media/{html.escape(asset)}" '
                 f'alt="PNG из фактического sendPhoto payload"></div>')
    else:
        media = ""
    keyboard_html = ""
    markup = call.get("reply_markup")
    if isinstance(markup, dict):
        buttons = [button.get("text", "") for row in markup.get("inline_keyboard", [])
                   for button in row if isinstance(button, dict)]
        if buttons:
            keyboard_html = '<div class="buttons">' + "".join(
                f'<span>{html.escape(str(button))}</span>' for button in buttons
            ) + "</div>"
    message = (f'<article class="message" style="--phone:{width}px"><small>{html.escape(label)}</small>'
               f'<div class="bubble">{content}</div>{keyboard_html}{media}'
               f'<details><summary>Реальный Bot API payload</summary><pre>{escaped_payload}</pre></details></article>')
    return message


async def generate() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = public_registry()
    coverage = list(
        csv.DictReader((ROOT / "reports/scenario-material-coverage.csv").open(encoding="utf-8-sig"))
    )
    sections: list[str] = []
    payloads: list[dict[str, object]] = []
    api_calls: list[dict[str, object]] = []

    async def add_scenario(
        story: str, seed: int, positions: tuple[int, ...], label: str, *, mixed: bool
    ) -> None:
        snapshot = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, story), registry
        ).snapshot
        for pos in positions:
            question = snapshot.questions[pos - 1]
            case_id = (f"coverage-{question.family_id}" if mixed else f"full-{story}-{seed}-q{pos}")
            calls = (
                await capture_mixed_problem(snapshot, pos, case_id)
                if mixed
                else await capture_scenario_session(snapshot, pos, case_id)
            )
            media_order = 0
            for call in calls:
                call.update(case=label, story=story, seed=seed, position=pos)
                api_calls.append(call)
                if call["method"] == "sendPhoto" and isinstance(call.get("filename"), str):
                    media_order += 1
                    payloads.append({
                        "label": label, "method": "sendPhoto", "filename": call["filename"],
                        "bytes": call.get("photo_bytes"), "story": story, "seed": seed,
                        "position": pos, "media_order": media_order,
                    })
            for w in WIDTHS:
                sections.append(
                    f'<section><h3>{html.escape(label)} · {story}, позиция {pos} · {w}px</h3><div class="row">'
                    + "".join(api_message_card(call, case_id, w) for call in calls)
                    + "</div></section>"
                )

    for story in STORIES:
        await add_scenario(story, 42, (1, 2, 3, 4, 5), "Полный сценарий", mixed=False)
    for row in coverage:
        await add_scenario(
            row["story"], int(row["seed"]), (int(row["position"]),),
            f"Покрытие · {row['family']}", mixed=True,
        )

    # These conversation states use real shared send_text/hint/solution presentation calls.
    for state, story in (("replay", "TYRES"), ("history", "FLAT")):
        snap = build_practice_plan(PracticeRequest(PracticeMode.FULL, 42, story), registry).snapshot
        q = snap.questions[0]
        examples = (
            ("Исходная задача", question_message(
                f"Повтор исходной задачи №{q.position}" if state == "replay" else "История · №1",
                q.condition, f"Правильный ответ: {q.canonical_answer}", position="Результат сохранён",
            )),
            ("Подсказка", hint_message(q.hints[0])),
            ("Разбор", solution_message(q.solution_steps, q.canonical_answer)),
        )
        for label, body in examples:
            case_id = f"{state}-{label.lower()}"
            calls = await capture_presentation_message(body, case_id)
            for call in calls:
                call.update(case=state, story=story, position=1)
                api_calls.append(call)
            for w in WIDTHS:
                sections.append(
                    f'<section><h3>{html.escape(state)} · {html.escape(label)} · {w}px</h3><div class="row">'
                    + "".join(api_message_card(call, case_id, w) for call in calls)
                    + "</div></section>"
                )

    html_doc = (
        """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OGE · офлайн-галерея payload</title><style>
body{margin:0;background:#eef2f7;color:#182434;font:15px/1.5 system-ui,sans-serif}header{padding:26px max(20px,calc((100vw - 1200px)/2));background:#13243a;color:white}h1{margin:0 0 8px}header p{max-width:850px;color:#d4deeb}main{max-width:1200px;margin:auto;padding:20px}section{margin:24px 0;padding:20px;background:#fff;border-radius:18px;box-shadow:0 4px 18px #14253b12}h3{margin:0 0 14px}.row{display:flex;gap:14px;align-items:flex-start;overflow:auto;padding-bottom:8px}.message{flex:0 0 min(var(--phone),calc(100vw - 64px));max-width:var(--phone);border:1px solid #d8e1ea;border-radius:16px;background:#f6f8fb;padding:10px;box-sizing:border-box}.message small{display:block;color:#52657a;margin:0 4px 8px}.bubble{background:white;border-radius:13px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;box-shadow:0 1px 3px #14253b14}.bubble b{color:#152d48}.bubble.media{padding:5px}.bubble img{display:block;width:100%;height:auto;border-radius:9px}details{margin:8px 4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#42546b;font-size:12px}a{display:inline-block;margin:8px;color:#1769aa}
</style><header><h1>ОГЭ · офлайн-галерея исходящих payload</h1><p>Карточки сняты с вызовов render_session и _send_problem, пропущенных через локальный aiogram BaseSession; подсказки, разбор, повтор и история используют общий send_text. PNG сохранены из исходящих sendPhoto. Это офлайн-перехват Bot API payload, не скриншоты Telegram и не подтверждение фактической доставки. ROUTE недоступен публично и не включён.</p><p>Ширины просмотра: 360, 390 и 430 px. В каждой карточке можно раскрыть точный payload.</p></header><main>"""
        + "\n".join(sections)
        + "</main></html>"
    )
    (OUT / "index.html").write_text(html_doc, encoding="utf-8")
    (OUT / "payloads.json").write_text(
        json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "bot-api-calls.json").write_text(
        json.dumps(api_calls, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Gallery: {OUT / 'index.html'}")
    print(
        f"Scenarios: {len(STORIES)} × five positions; coverage rows: {len(coverage)}; payload PNGs: {len(payloads)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if args.output != OUT:
        OUT = args.output
    asyncio.run(generate())
