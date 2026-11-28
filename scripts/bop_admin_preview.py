"""Build a static, synthetic gallery from bop Admin's production Telegram renderers."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "bop-admin-preview"
sys.path.insert(0, str(ROOT))

from app.admin.screens import render_screen  # noqa: E402

MOSCOW = ZoneInfo("Europe/Moscow")
PREVIEW_NOW = datetime(2026, 11, 28, 12, 34, tzinfo=MOSCOW)
DATABASE_TZ = ZoneInfo("UTC")


REPORT_WINDOW = SimpleNamespace(
    start=datetime(2026, 11, 21, tzinfo=MOSCOW),
    end=datetime(2026, 11, 28, tzinfo=MOSCOW),
)
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
            {"mode": "mixed", "users": 22, "answered": 240, "submitted": 9},
            {"mode": "adaptive", "users": 12, "answered": 188, "submitted": 8},
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
                "last_activity": PREVIEW_NOW.astimezone(DATABASE_TZ)
                - timedelta(days=days, minutes=17),
            }
            for identity, days in zip(LEARNER_IDS, [0, 1, 4, 5], strict=True)
        ]
    },
    "learner": {
        "found": True,
        "last_activity": PREVIEW_NOW - timedelta(minutes=17),
        "days": 9,
        "solved": 38,
        "answered": 51,
        "numbers": [1, 2, 4, 7, 8, 12],
        "submitted": 3,
        "graded": 3,
        "points": 14,
    },
    "tasks": {
        "rows": [
            {"number": number, "users": 63 - number, "answered": 62 - number, "solved": 47 - number}
            for number in range(1, 20)
        ]
    },
    "types": {
        "rows": [
            {
                "family_id": "OGE07-DIRECT",
                "users": 18,
                "answered": 46,
                "solved": 32,
                "hinted": 7,
                "assistance_known": 44,
                "hint_known": 45,
            },
            {
                "family_id": "OGE07-REVERSE",
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
                "family_id": "OGE07-DIRECT",
                "answered": 4,
                "solved": 3,
                "repeat_errors": 1,
            },
            {
                "number": 12,
                "family_id": "OGE12-RATIO",
                "answered": 3,
                "solved": 2,
                "repeat_errors": 1,
            },
            {
                "number": 4,
                "family_id": "OGE04-TABLE",
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
            {"number": 13, "title": "Задание №13", "zero": 5, "one": 4, "two": 2},
            {"number": 14, "title": "Задание №14", "zero": 2, "one": 3, "two": 2},
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
    cases = [(screen, screen, fixture, "synthetic") for screen, fixture in FIXTURES.items()] + [
        (
            "written-13",
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
                        "number": 13,
                        "subtype_id": "OGE13-LINEAR-EQUATION",
                        "title": "Линейное уравнение",
                        "zero": 2,
                        "one": 1,
                        "two": 1,
                    },
                    {
                        "number": 13,
                        "subtype_id": "OGE13-QUADRATIC-EQUATION",
                        "title": "Квадратное уравнение",
                        "zero": 1,
                        "one": 0,
                        "two": 1,
                    },
                ],
                "more": True,
            },
            "synthetic",
        ),
        ("home-timeout", "home", {"unavailable": "timeout"}, "unavailable"),
        ("learners-empty", "learners", {"rows": []}, "empty"),
        ("system-unconfigured", "system", {"unavailable": "unconfigured"}, "unavailable"),
    ]
    report_screens = set(FIXTURES) - {"tools"}
    window_meta = {
        "period": "7",
        "timezone": "Europe/Moscow",
        "start": REPORT_WINDOW.start.isoformat(),
        "end": REPORT_WINDOW.end.isoformat(),
    }
    payloads = []
    for case, screen, fixture, fixture_kind in cases:
        data = fixture.copy()
        context: dict[str, Any] = {
            "revision": "preview",
            "period": "7",
            "release": "synthetic-preview",
            "companion_status": "unavailable",
        }
        if screen in report_screens:
            context.update(window=REPORT_WINDOW, updated_at=PREVIEW_NOW)
        if screen == "learner":
            context["learner_id"] = str(LEARNER_IDS[0])
        if screen in {"types", "task"}:
            context["number"] = 7
        if screen == "task":
            context["family_id"] = "OGE07-DIRECT"
        if case == "written-13":
            context["number"] = 13
        text, markup = render_screen(screen, data, **context)
        record = {
            "case": case,
            "screen": screen,
            "fixture_kind": fixture_kind,
            "report_data": data,
            "report_window": window_meta if screen in report_screens else None,
            "updated_at": PREVIEW_NOW.isoformat() if screen in report_screens else None,
            "text": text,
            "reply_markup": markup.model_dump(mode="json", exclude_none=True),
        }
        payloads.append(record)
        (payload_dir / f"{case}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    data = json.dumps(payloads, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = PAGE.replace("__PAYLOADS__", data)
    (OUT / "index.html").write_text(page, encoding="utf-8")


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
    .bubble { width: 100%; padding: 12px 13px 10px; border-radius: 14px 14px 14px 4px;
      background: white; box-shadow: 0 1px 2px #26362912; }
    .message { font-size: 14px; line-height: 1.48; white-space: pre-wrap; overflow-wrap: anywhere; }
    .message b, .message strong { font-weight: 700; }
    .message i { font-style: italic; }
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
      <p class="eyebrow">bop Math · закрытая панель</p>
      <h1>Админские экраны в Telegram</h1>
      <p class="intro">12 экранов + экран №13 + 3 состояния · production renderer</p>
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
    const names = {home:'Обзор',usage:'Использование',learners:'Ученики',learner:'Карточка ученика',
      tasks:'Задания',types:'Типы заданий',task:'Статистика номера',replays:'Повторы',
      written:'Письменные работы',system:'Система',cost:'AI и расходы',tools:'Точные проверки'};
    const cases = {'written-13':'Письменные работы · №13 и типы',
      'home-timeout':'Обзор · тайм-аут', 'learners-empty':'Ученики · пустой период',
      'system-unconfigured':'Система · не настроена'};
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
      title.textContent = cases[item.case] || names[item.screen] || item.screen;
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = item.fixture_kind.toUpperCase();
      head.append(title,badge);
      const chat = document.createElement('div'); chat.className = 'chat';
      const bubble = document.createElement('div'); bubble.className = 'bubble';
      const message = document.createElement('div'); message.className = 'message';
      safeTelegramText(item.text, message);
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
    build()
