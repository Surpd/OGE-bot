"""Build a static, synthetic gallery from bop Admin's production Telegram renderer."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

from PIL import Image
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "bop-admin-visual"
sys.path.insert(0, str(ROOT))

from app.admin.presentation import render_admin_view  # noqa: E402
from app.admin.service import ReportWindow  # noqa: E402

MOSCOW = ZoneInfo("Europe/Moscow")
PREVIEW_NOW = datetime(2026, 11, 28, 12, 34, tzinfo=MOSCOW)
DATABASE_TZ = ZoneInfo("UTC")


REPORT_WINDOW = ReportWindow.at("7", PREVIEW_NOW)
COHORT_END = date(2026, 11, 15)
LEARNER_IDS = [
    UUID("17a8f719-f34a-4aa3-8e94-bd7f4d77eb01"),
    UUID("17a8f719-f34a-4aa3-8e94-bd7f4d77eb02"),
    UUID("17a8f719-f34a-4aa3-8e94-bd7f4d77eb03"),
    UUID("17a8f719-f34a-4aa3-8e94-bd7f4d77eb04"),
]

FIXTURES: dict[str, dict[str, Any]] = {
    "home": {
        "registered": 126,
        "active": 34,
        "first": 11,
        "repeat_days": 18,
        "answered": 428,
        "attempts": 506,
        "graded": 17,
        "errors": 2,
        "known_cost": Decimal("0.0184"),
        "unknown_cost": 2,
    },
    "usage": {
        "registered": 126,
        "active": 34,
        "first": 11,
        "repeat_days": 18,
        "answered": 428,
        "attempts": 506,
        "graded": 17,
        "errors": 2,
        "known_cost": Decimal("0.0184"),
        "unknown_cost": 2,
        "modes": [
            {"mode": "personal", "users": 8, "answered": 64, "submitted": 0},
            {"mode": "mixed", "users": 6, "answered": 78, "submitted": 0},
            {"mode": "number", "users": 5, "answered": 70, "submitted": 0},
            {"mode": "family", "users": 4, "answered": 54, "submitted": 0},
            {"mode": "full_part", "users": 3, "answered": 95, "submitted": 0},
            {"mode": "scenario_single", "users": 2, "answered": 22, "submitted": 0},
            {"mode": "scenario_full", "users": 4, "answered": 42, "submitted": 0},
            {"mode": "unknown", "users": 2, "answered": 3, "submitted": 0},
        ],
        "retention": {
            "returned": 18,
            "eligible": 29,
            "first_day": COHORT_END - timedelta(days=7),
            "last_day": COHORT_END - timedelta(days=1),
        },
        "days": [
            {"day": REPORT_WINDOW.start.date() + timedelta(days=offset), "active": active}
            for offset, active in enumerate([8, 12, 10, 18, 16, 23, 34])
        ],
    },
    "learners": {
        "rows": [
            {
                "user_id": identity,
                "display_name": name,
                "username": username,
                "last_activity": PREVIEW_NOW.astimezone(DATABASE_TZ)
                - timedelta(days=days, minutes=17),
            }
            for identity, days, name, username in zip(
                LEARNER_IDS,
                [0, 1, 4, 5],
                ["Анна · демо", "Михаил · демо", None, "Очень длинное имя профиля для проверки"],
                ["preview_anna", None, None, "preview_long_profile"],
                strict=True,
            )
        ]
    },
    "learner": {
        "found": True,
        "display_name": "Анна · демо",
        "username": "preview_anna",
        "last_activity": PREVIEW_NOW - timedelta(days=1, minutes=17),
        "days": 6,
        "solved": 24,
        "answered": 31,
        "numbers": [1, 2, 4, 7, 8, 12],
        "submitted": 3,
        "graded": 3,
        "points": 6,
    },
    "tasks": {
        "rows": [
            {
                "number": number,
                "users": 24 - number,
                "answered": 62 - number,
                "solved": 47 - number,
            }
            for number in range(1, 20)
        ]
    },
    "types": {
        "rows": [
            {
                "family_id": "OGE07-C01",
                "users": 18,
                "answered": 46,
                "solved": 32,
                "hinted": 7,
                "assistance_known": 44,
                "hint_known": 45,
            },
            {
                "family_id": "OGE07-C02",
                "users": 11,
                "answered": 27,
                "solved": 17,
                "hinted": 5,
                "assistance_known": 26,
                "hint_known": 26,
            },
        ],
        "more": False,
    },
    "task": {
        "users": 24,
        "issued": 92,
        "answered": 71,
        "solved": 49,
        "first_correct": 31,
        "unassisted": 39,
        "first_unassisted": 24,
        "novel_first_unassisted": 17,
        "novelty_unknown": 2,
        "assistance_unknown": 3,
        "assistance_known": 68,
        "hinted": 11,
        "hint_known": 18,
        "skipped": 6,
        "solution_views": 14,
        "repeat_errors": 8,
        "replay_answered": 18,
        "replay_solved": 13,
    },
    "replays": {
        "rows": [
            {
                "number": 7,
                "family_id": "OGE07-C01",
                "answered": 4,
                "solved": 3,
                "repeat_errors": 1,
            },
            {
                "number": 12,
                "family_id": "OGE08-R02",
                "answered": 3,
                "solved": 2,
                "repeat_errors": 1,
            },
            {
                "number": 4,
                "family_id": "OGE04-F001",
                "answered": 5,
                "solved": 4,
                "repeat_errors": 1,
            },
        ],
        "more": True,
    },
    "written": {
        "issued": 22,
        "issues_submitted": 16,
        "submitted": 18,
        "revisions": 4,
        "graded": 11,
        "unreadable": 2,
        "uncertain": 1,
        "error": 1,
        "pending": 3,
        "rows": [
            {"number": 20, "title": "Задание №20", "zero": 3, "one": 3, "two": 1},
            {"number": 21, "title": "Задание №21", "zero": 1, "one": 2, "two": 1},
        ],
        "more": False,
    },
    "system": {
        "errors": 2,
        "operations": [
            {"status": "ok", "count": 184},
            {"status": "retry", "count": 3},
            {"status": "error", "count": 2},
        ],
    },
    "cost": {
        "known_cost": Decimal("0.0184"),
        "unknown_cost": 2,
        "diagnostics": 12,
        "diagnostic_cost": Decimal("0.0032"),
        "diagnostic_unknown": 1,
        "spent": Decimal("0.0204"),
        "held": Decimal("0.0040"),
        "month_start": datetime(2026, 11, 1, tzinfo=DATABASE_TZ),
        "month_end": datetime(2026, 12, 1, tzinfo=DATABASE_TZ),
        "graded": 17,
        "written_cost": Decimal("0.0187"),
        "unknown_written": 1,
        "budget": Decimal("2.0000"),
        "available": Decimal("1.9756"),
        "known_cost_per_result": Decimal("0.0011"),
    },
    "tools": {},
}


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload_dir = OUT / "payloads"
    payload_dir.mkdir(exist_ok=True)
    assets_dir = OUT / "images"
    assets_dir.mkdir(exist_ok=True)
    usage_month = ReportWindow.at("28", PREVIEW_NOW)
    first, last = usage_month.mature_cohorts()
    cases = [(screen, screen, fixture, "Заполнено") for screen, fixture in FIXTURES.items()] + [
        ("usage-details", "usage", FIXTURES["usage"], "Подробнее"),
        ("cost-details", "cost", FIXTURES["cost"], "Подробнее"),
        ("system-details", "system", FIXTURES["system"], "Подробнее"),
        ("learner-details", "learner", FIXTURES["learner"], "Подробнее"),
        ("learners-empty", "learners", {"rows": []}, "Пусто"),
        (
            "learner-long-name",
            "learner",
            {**FIXTURES["learner"], "display_name": "ДлинноеИмя" * 12, "username": None},
            "Длинное имя",
        ),
        (
            "usage-today-empty",
            "usage",
            {"registered": 126, "active": 0, "modes": [], "days": [], "retention": {}},
            "Сегодня · пусто",
        ),
        (
            "usage-28",
            "usage",
            {
                **FIXTURES["usage"],
                "active": 61,
                "first": 31,
                "repeat_days": 43,
                "answered": 1284,
                "attempts": 1534,
                "days": [
                    {"day": usage_month.start.date() + timedelta(days=offset), "active": users}
                    for offset, users in enumerate(
                        [
                            7,
                            11,
                            10,
                            13,
                            16,
                            19,
                            20,
                            15,
                            14,
                            17,
                            21,
                            23,
                            24,
                            20,
                            15,
                            19,
                            22,
                            18,
                            23,
                            30,
                            27,
                            19,
                            22,
                            21,
                            29,
                            32,
                            28,
                            37,
                        ]
                    )
                ],
                "modes": [
                    {**mode, "users": mode["users"] * 2, "answered": mode["answered"] * 3}
                    for mode in FIXTURES["usage"]["modes"]
                ],
                "retention": {
                    "returned": 32,
                    "eligible": 48,
                    "first_day": first.date(),
                    "last_day": last.date() - timedelta(days=1),
                },
            },
            "28 дней",
        ),
        (
            "written-23",
            "written",
            {
                "issued": 8,
                "issues_submitted": 6,
                "submitted": 7,
                "revisions": 1,
                "graded": 5,
                "unreadable": 1,
                "uncertain": 0,
                "error": 0,
                "pending": 1,
                "rows": [
                    {
                        "number": 23,
                        "subtype_id": "OGE23-PRACTICAL-CALCULATION",
                        "title": "Практический расчёт",
                        "zero": 1,
                        "one": 1,
                        "two": 1,
                    },
                    {
                        "number": 23,
                        "subtype_id": "OGE23-TEXT-MODELLING",
                        "title": "Математическая модель условия",
                        "zero": 1,
                        "one": 0,
                        "two": 1,
                    },
                ],
                "more": True,
            },
            "Заполнено",
        ),
        (
            "written-25",
            "written",
            {
                "issued": 9,
                "issues_submitted": 6,
                "submitted": 7,
                "revisions": 1,
                "graded": 6,
                "pending": 1,
                "rows": [
                    {
                        "number": 25,
                        "subtype_id": "OGE25-PLANE-GEOMETRY",
                        "title": "Планиметрическая задача",
                        "zero": 1,
                        "one": 2,
                        "two": 3,
                    }
                ],
            },
            "Заполнено",
        ),
        (
            "home-today",
            "home",
            {
                "registered": 126,
                "active": 6,
                "first": 2,
                "answered": 14,
                "attempts": 17,
                "known_cost": Decimal(0),
            },
            "Сегодня",
        ),
        ("home-empty", "home", {}, "Пусто"),
        ("usage-empty", "usage", {"modes": [], "days": [], "retention": {}}, "Пусто"),
        ("tasks-empty", "tasks", {"rows": []}, "Пусто"),
        ("types-empty", "types", {"rows": []}, "Пусто"),
        ("learner-empty", "learner", {"found": True}, "Пусто"),
        ("learner-not-found", "learner", {"found": False}, "Ученик недоступен"),
        ("written-empty", "written", {"rows": []}, "Пусто"),
        (
            "cost-empty",
            "cost",
            {
                "known_cost": Decimal(0),
                "spent": Decimal(0),
                "held": Decimal(0),
                "budget": FIXTURES["cost"]["budget"],
                "available": FIXTURES["cost"]["budget"],
                "month_start": FIXTURES["cost"]["month_start"],
                "month_end": FIXTURES["cost"]["month_end"],
            },
            "Пусто",
        ),
        ("replays-empty", "replays", {"rows": []}, "Пусто"),
        ("home-timeout", "home", {"unavailable": "timeout"}, "Источник недоступен"),
        ("system-unconfigured", "system", {"unavailable": "unconfigured"}, "Источник недоступен"),
        ("tools-current", "tools", {}, "Инструменты"),
    ]
    report_screens = set(FIXTURES) - {"tools"}
    payloads = []
    for case, screen, fixture, fixture_kind in cases:
        data = fixture.copy()
        period = {"home-today": "today", "usage-today-empty": "today", "usage-28": "28"}.get(
            case, "7"
        )
        window = ReportWindow.at(period, PREVIEW_NOW)
        context: dict[str, Any] = {
            "revision": "preview",
            "period": period,
            "release": "synthetic-preview",
            "companion_status": "unavailable" if case == "system-unconfigured" else "ready",
            "expanded": case.endswith("-details"),
        }
        if screen in report_screens:
            context.update(window=window, updated_at=PREVIEW_NOW)
        if screen == "learner":
            context["learner_id"] = str(LEARNER_IDS[0])
        if screen in {"types", "task"}:
            context["number"] = 7
        if screen == "task":
            context["family_id"] = "OGE07-C01"
        if case in {"written-23", "written-25"}:
            context["number"] = int(case.split("-")[1])
        if screen in {"learners", "tasks", "types", "written", "replays"}:
            context["page"] = 0
        if case in {"types", "types-empty"}:
            context["sort"] = "help" if case == "types" else "sample"
        if case == "learner-not-found":
            context["learner_id"] = "preview-not-found"
        view = render_admin_view(screen, data, **context)
        text, markup = view.text, view.markup
        image_path = None
        if view.photo is not None:
            image_path = f"images/{case}.png"
            (OUT / image_path).write_bytes(view.photo)
        record = {
            "case": case,
            "screen": screen,
            "fixture_kind": fixture_kind,
            "report_data": data,
            "report_window": {
                "period": period,
                "timezone": "Europe/Moscow",
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            }
            if screen in report_screens
            else None,
            "updated_at": PREVIEW_NOW.isoformat() if screen in report_screens else None,
            "text": text,
            "caption": view.caption,
            "image": image_path,
            "reply_markup": markup.model_dump(mode="json", exclude_none=True),
        }
        payloads.append(record)
        (payload_dir / f"{case}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    expected_payloads = {f"{record['case']}.json" for record in payloads}
    for file in payload_dir.glob("*.json"):
        if file.name not in expected_payloads:
            file.unlink()
    expected_images = {Path(record["image"]).name for record in payloads if record["image"]}
    for file in assets_dir.glob("*.png"):
        if file.name not in expected_images:
            file.unlink()

    data = json.dumps(payloads, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = PAGE.replace("__PAYLOADS__", data)
    (OUT / "index.html").write_text(page, encoding="utf-8")


def capture_gallery(chrome: Path) -> None:
    if not chrome.is_file():
        raise FileNotFoundError("Pass the path to a Chromium executable with --chromium")
    screenshots = OUT / "screenshots"
    screenshots.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="bop-admin-gallery-", ignore_cleanup_errors=True
    ) as profile:
        chrome_process = subprocess.Popen(
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                (OUT / "index.html").resolve().as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            port_file = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not port_file.exists() and time.monotonic() < deadline:
                if chrome_process.poll() is not None:
                    raise RuntimeError("Local Chromium exited before opening the gallery")
                time.sleep(0.1)
            if not port_file.exists():
                raise TimeoutError("Local Chromium did not expose its headless preview")
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
            targets = json.load(urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5))
            target = next(item for item in targets if item.get("type") == "page")
            with connect(
                target["webSocketDebuggerUrl"],
                max_size=None,
                open_timeout=5,
            ) as browser:
                next_id = 0

                def command(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                    nonlocal next_id
                    next_id += 1
                    command_id = next_id
                    browser.send(
                        json.dumps({"id": command_id, "method": method, "params": params or {}})
                    )
                    while True:
                        response = json.loads(browser.recv(timeout=10))
                        if response.get("id") == command_id:
                            if "error" in response:
                                raise RuntimeError(f"Chromium preview command failed: {method}")
                            return response.get("result", {})

                command("Page.enable")
                command("Runtime.enable")
                for width in (360, 390, 430):
                    target_path = screenshots / f"mobile-{width}.png"
                    command(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": width, "height": 850, "deviceScaleFactor": 1, "mobile": True},
                    )
                    command("Page.navigate", {"url": (OUT / "index.html").resolve().as_uri()})
                    deadline = time.monotonic() + 15
                    while True:
                        state = command(
                            "Runtime.evaluate",
                            {
                                "expression": (
                                    "JSON.stringify({ready:document.readyState,"
                                    "width:document.documentElement.clientWidth,"
                                    "hasScreens:!!document.querySelector('.screen'),"
                                    "images:[...document.images].every(image=>"
                                    "image.complete&&image.naturalWidth>0)})"
                                ),
                                "returnByValue": True,
                            },
                        )
                        payload = json.loads(state["result"]["value"])
                        if (
                            payload["ready"] == "complete"
                            and payload["hasScreens"]
                            and payload["width"] == width
                            and payload["images"]
                        ):
                            break
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Gallery did not finish laying out at {width}px")
                        time.sleep(0.1)
                    layout = command("Page.getLayoutMetrics")["cssContentSize"]
                    if layout["width"] != width:
                        raise RuntimeError(f"Expected a {width}px preview, got {layout['width']}px")
                    result = command(
                        "Runtime.evaluate",
                        {
                            "expression": (
                                "[...document.querySelectorAll('.message,.key')].every("
                                "el=>el.scrollWidth<=el.clientWidth&&(!el.classList.contains"
                                "('key')||(el.offsetWidth>=44&&el.offsetHeight>=44)))"
                            ),
                            "returnByValue": True,
                        },
                    )
                    if result["result"]["value"] is not True:
                        raise RuntimeError(
                            f"Clipped content or undersized Telegram button at {width}px"
                        )
                    screenshot = command(
                        "Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
                    )
                    target_path.write_bytes(base64.b64decode(screenshot["data"], validate=True))
                    with Image.open(target_path) as image:
                        if image.width != width or image.height != layout["height"]:
                            raise RuntimeError(
                                f"Expected {width}px full-page image, "
                                f"got {image.width}×{image.height}"
                            )
                        print(f"{target_path.name}: {image.width}×{image.height} px")
                browser.send(json.dumps({"id": next_id + 1, "method": "Browser.close"}))
        finally:
            try:
                chrome_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                chrome_process.terminate()
                chrome_process.wait(timeout=10)


PAGE = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <link rel="icon" href="data:,">
  <title>bop Admin · Telegram preview</title>
  <style>
    :root {
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --ink: #1f3029; --muted: #718078; --paper: #f4f2e9; --card: #fffefa;
      --green: #24664d; --green-soft: #e8f2e9; --line: #e5e6dc; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--paper); color: var(--ink); overflow-wrap: break-word; }
    .shell { max-width: 1100px; margin-inline: auto; padding: 26px 18px 48px; }
    header { margin: 0 0 22px; }
    .eyebrow { margin: 0 0 5px; color: var(--green); font-weight: 700; font-size: 12px;
      letter-spacing: .09em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(24px, 6vw, 32px); line-height: 1.15; text-wrap: balance; }
    .intro { margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .shot-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .shot-links a { display: inline-flex; min-height: 36px; align-items: center; padding: 0 11px;
      border: 1px solid #d6e3d7; border-radius: 999px; color: var(--green); background: #fffefa;
      font-size: 12px; font-weight: 650; text-decoration: none; }
    .gallery { display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 14px; }
    .screen { min-width: 0; overflow: clip; border: 1px solid var(--line); border-radius: 18px;
      background: var(--card); box-shadow: 0 3px 16px #253b2a0a; }
    .screen-head { display: flex; justify-content: space-between; align-items: center; gap: 8px;
      padding: 12px 14px; border-bottom: 1px solid var(--line); }
    .screen-head h2 { margin: 0; font-size: 14px; font-weight: 650; }
    .badge { flex: none; border-radius: 999px; padding: 4px 8px; color: #496b55;
      background: var(--green-soft); font-size: 10px; font-weight: 700; }
    .chat { padding: 14px 12px; background: #eef3ec; }
    .bubble { width: 100%; padding: 11px 11px 9px; border-radius: 14px 14px 14px 4px;
      background: white; box-shadow: 0 1px 2px #26362912; }
    .message { font-size: 14px; line-height: 1.48; white-space: pre-wrap; overflow-wrap: anywhere; }
    .message b, .message strong { font-weight: 700; }
    .message i { font-style: italic; }
    .message img { display: block; width: min(100%, 400px); height: auto; margin: -1px auto 9px;
      border-radius: 6px; }
    .message:empty { display: none; }
    .time { margin-top: 6px; text-align: right; color: #8b9b90; font-size: 10px; }
    .keyboard { display: grid; gap: 5px; margin-top: 9px; }
    .keyrow { display: grid; gap: 5px;
      grid-auto-columns: minmax(0, 1fr); grid-auto-flow: column; }
    .key { display: flex; min-width: 0; min-height: 44px;
      align-items: center; justify-content: center;
      padding: 7px 5px; border: 0; border-radius: 7px; background: #fff; color: #287254;
      font: inherit; font-size: 13px; font-weight: 600; line-height: 1.25;
      text-align: center; overflow-wrap: anywhere; }
    .key.success { background: #287254; color: #fff; }
    a.key { text-decoration: none; }
    .raw { padding: 0 13px 12px; color: var(--muted); font-size: 10px; }
    .raw summary { cursor: pointer; min-height: 32px; display: flex; align-items: center; }
    .raw code { display: block; padding: 8px; border-radius: 8px; background: #f3f4ee;
      white-space: pre-wrap; overflow-wrap: anywhere; }
    @media (max-width: 359px) {
      .shell { padding-inline: 12px; }
      .key { font-size: 12px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <p class="eyebrow">bop Math · аналитика</p>
      <h1>Панель в Telegram</h1>
      <p class="intro">Синтетические данные · реальные PNG, сообщения и клавиатуры</p>
      <nav class="shot-links" aria-label="Скриншоты мобильной галереи">
        <a href="screenshots/mobile-360.png">360 px</a>
        <a href="screenshots/mobile-390.png">390 px</a>
        <a href="screenshots/mobile-430.png">430 px</a>
      </nav>
    </header>
    <section class="gallery" id="gallery" aria-label="Галерея экранов"></section>
  </main>
  <script>
    const screens = __PAYLOADS__;
    const names = {
      home:'Обзор', usage:'Активность', learners:'Ученики', learner:'Карточка ученика',
      tasks:'Задания по номерам', types:'Типы заданий', task:'Результаты по номеру',
      replays:'Повторы ошибок',
      written:'Письменные работы', system:'Состояние системы',
      cost:'ИИ и расходы', tools:'Инструменты'
    };
    function caseTitle(item) {
      if (/^written-\d+$/.test(item.case))
        return `Письменные работы · №${item.case.split('-')[1]}`;
      if (item.case === 'home-today') return 'Обзор · сегодня';
      if (item.case === 'learner-not-found') return 'Карточка ученика · недоступна';
      if (item.fixture_kind !== 'Заполнено' && item.fixture_kind !== 'Инструменты')
        return `${names[item.screen] || item.screen} · ${item.fixture_kind.toLowerCase()}`;
      return names[item.screen] || item.screen;
    }
    function safeTelegramText(source, target) {
      const parsed = new DOMParser().parseFromString(`<body>${source}</body>`, 'text/html').body;
      function copy(node, parent) {
        for (const child of node.childNodes) {
          if (child.nodeType === Node.TEXT_NODE) {
            parent.append(document.createTextNode(child.nodeValue));
          }
          else if (child.nodeType === Node.ELEMENT_NODE) {
            const tag = ['B','STRONG','I','EM','CODE','PRE'].includes(child.tagName)
              ? child.tagName.toLowerCase() : 'span';
            const el = document.createElement(tag);
            copy(child, el);
            parent.append(el);
          }
        }
      }
      copy(parsed, target);
    }
    const gallery = document.querySelector('#gallery');
    for (const item of screens) {
      const card = document.createElement('article'); card.className = 'screen';
      const head = document.createElement('div'); head.className = 'screen-head';
      const title = document.createElement('h2');
      title.textContent = caseTitle(item);
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = item.fixture_kind;
      head.append(title,badge);
      const chat = document.createElement('div'); chat.className = 'chat';
      const bubble = document.createElement('div'); bubble.className = 'bubble';
      const message = document.createElement('div'); message.className = 'message';
      if (item.image) {
        const photo = document.createElement('img');
        photo.src = item.image;
        photo.alt = `Сводка ${names[item.screen] || item.screen}`;
        message.append(photo);
        if (item.caption) safeTelegramText(item.caption, message);
      } else safeTelegramText(item.text, message);
      const time = document.createElement('div');
      time.className = 'time'; time.textContent = '12:34';
      bubble.append(message,time);
      const keyboard = document.createElement('div'); keyboard.className = 'keyboard';
      for (const row of item.reply_markup.inline_keyboard || []) {
        const rowEl = document.createElement('div'); rowEl.className = 'keyrow';
        for (const button of row) {
          const key = document.createElement(button.url ? 'a' : 'div'); key.className = 'key';
          if (button.style) key.classList.add(button.style);
          key.textContent = button.text;
          if (button.url) { key.href = button.url; key.rel = 'noreferrer'; }
          if (button.callback_data) key.title = `callback_data: ${button.callback_data}`;
          rowEl.append(key);
        }
        keyboard.append(rowEl);
      }
      bubble.append(keyboard); chat.append(bubble);
      const details = document.createElement('details'); details.className = 'raw';
      const summary = document.createElement('summary');
      summary.textContent = 'Фактические callback_data';
      const code = document.createElement('code');
      code.textContent = (item.reply_markup.inline_keyboard || []).flat().map(x =>
        `${x.text}: ${x.callback_data || x.url || 'без действия'}`).join('\n');
      details.append(summary,code); card.append(head,chat,details); gallery.append(card);
    }
  </script>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", type=Path, help="Capture mobile PNGs with this executable")
    options = parser.parse_args()
    build()
    if options.chromium:
        capture_gallery(options.chromium.resolve())
