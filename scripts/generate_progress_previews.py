"""Generate deterministic fictional Telegram progress dashboard previews."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image

from app.bot.progress_image import render_progress_image
from app.persistence.training_insights import summarize

OUTPUT = Path("reports/previews")


def _record(
    index: int,
    outcome: str,
    attempts: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    number = index % 14 + 1
    family = "OGE15:PAPER" if number <= 5 else f"OGE{number:02}-F001"
    return {
        "number": number,
        "family_id": family,
        "outcome": outcome,
        "attempt_records": attempts,
        "issued_at": datetime(2026, 11, 14, tzinfo=UTC) - timedelta(hours=107 - index),
        "condition": f"Учебный пример {index + 1}",
        **extra,
    }


def demo_insights() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index in range(14):
        records.append(
            _record(
                index,
                "solved",
                [
                    {"attempt_no": 1, "is_correct": True, "used_hint": False},
                ],
            )
        )
    for index in range(6):
        records.append(
            _record(
                14 + index,
                "solved",
                [
                    {"attempt_no": 1, "is_correct": False, "used_hint": False},
                    {"attempt_no": 2, "is_correct": True, "used_hint": True},
                ],
            )
        )
    for index in range(4):
        records.append(
            _record(
                20 + index,
                "solved",
                [
                    {"attempt_no": 1, "is_correct": False},
                    {"attempt_no": 2, "is_correct": True},
                ],
            )
        )
    for index in range(8):
        records.append(
            _record(
                24 + index,
                "failed",
                [
                    {"attempt_no": 1, "is_correct": False},
                    {"attempt_no": 2, "is_correct": False},
                ],
            )
        )
    for index in range(35):
        attempts = [{"attempt_no": 1, "is_correct": False}] if index < 7 else []
        records.append(_record(32 + index, "skipped", attempts))
    for index in range(5):
        attempts = [{"attempt_no": 1, "is_correct": False}] if index < 3 else []
        records.append(_record(67 + index, "solution_viewed", attempts, solution_viewed=True))
    insights = summarize(records)
    assert insights["total"]["completed"] == 72
    assert insights["total"]["skipped"] == 35
    assert insights["total"]["unassisted_correct"] == 14
    assert insights["total"]["assisted_correct"] == 6
    assert insights["total"]["unknown_assistance"] == 4
    assert insights["total"]["failed"] == 8
    assert insights["total"]["solutions_viewed"] == 5
    return insights


def generate() -> list[Path]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    insights = demo_insights()
    first_history = dict(insights)
    first_history["history"] = [
        insights["history"][14],  # solved with a hint after a wrong attempt
        insights["history"][20],  # correct attempt, legacy hint usage is unknown
        insights["history"][24],  # two errors
        insights["history"][32],  # skipped
    ]
    first_history["page_total"] = len(insights["history"])

    error_page = dict(insights)
    error_page["errors"] = [
        insights["history"][14],  # wrong first answer, then correct with a hint
        insights["history"][24],  # two wrong answers
        insights["history"][67],  # opened solution after an error
        insights["history"][20],  # second attempt correct; hint usage is unknown
    ]
    error_page["page_total"] = len(insights["errors"])

    empty = summarize([])
    pages = [
        ("progress-dashboard-overview.png", insights, "summary"),
        ("progress-dashboard-numbers-1-7.png", insights, "numbers:0"),
        ("progress-dashboard-numbers-8-14.png", insights, "numbers:7"),
        ("progress-dashboard-history.png", first_history, "history:0"),
        ("progress-dashboard-errors.png", error_page, "errors:0"),
        ("progress-dashboard-empty.png", empty, "summary"),
    ]
    output: list[Path] = []
    for filename, data, page in pages:
        path = OUTPUT / filename
        rendered = render_progress_image(data, page)
        path.write_bytes(rendered)
        output.append(path)
        with Image.open(io.BytesIO(rendered)) as image:
            reduced = image.convert("RGB").resize(
                (375, round(image.height * 375 / image.width)), Image.Resampling.LANCZOS
            )
        reduced_path = OUTPUT / f"{path.stem}-375.png"
        reduced.save(reduced_path, format="PNG", optimize=True, compress_level=9)
        output.append(reduced_path)
    return output


if __name__ == "__main__":
    for item in generate():
        print(f"{item} ({item.stat().st_size} bytes)")
