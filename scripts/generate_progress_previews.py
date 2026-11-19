"""Generate deterministic fictional previews for the unified progress screen."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from app.bot.progress_image import render_progress_image
from app.persistence.training_insights import NUMBERS, summarize

OUTPUT = Path("reports/previews")


def _record(number: int, index: int, outcome: str, correct: bool = False) -> dict[str, Any]:
    family = "OGE15:PAPER" if number <= 5 else f"OGE{number:02}-F001"
    attempts = (
        [{"attempt_no": 1, "is_correct": True, "used_hint": False}]
        if correct
        else [{"attempt_no": 1, "is_correct": False, "used_hint": False}]
    )
    if outcome in {"skipped", "solution_viewed"} and index % 2 == 0:
        attempts = []
    return {
        "number": number,
        "family_id": family,
        "outcome": outcome,
        "attempt_records": attempts,
        "issued_at": datetime(2026, 11, 14, tzinfo=UTC),
        "condition": f"Демонстрационная задача {number}.{index + 1}",
    }


def demo_insights(kind: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if kind == "partial":
        records.extend(
            _record(6, i, "solved" if i < 3 else "failed", correct=i < 3) for i in range(4)
        )
        records.extend(
            _record(11, i, "solved" if i < 2 else "failed", correct=i < 2) for i in range(5)
        )
        records.extend(_record(14, i, "skipped") for i in range(3))
    elif kind == "full":
        for number in NUMBERS:
            answered = 5 + number % 4
            correct_count = (number * 3) % (answered + 1)
            records.extend(
                _record(
                    number,
                    index,
                    "solved" if index < correct_count else "failed",
                    correct=index < correct_count,
                )
                for index in range(answered)
            )
            records.extend(
                _record(number, index + answered, "skipped") for index in range(number % 3)
            )
    elif kind != "empty":
        raise ValueError(f"Unknown preview kind: {kind}")
    return summarize(records)


def generate() -> list[Path]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    output: list[Path] = []
    for kind in ("empty", "partial", "full"):
        png = render_progress_image(demo_insights(kind))
        path = OUTPUT / f"progress-{kind}.png"
        path.write_bytes(png)
        output.append(path)
        with Image.open(path) as image:
            for width in (360, 390):
                resized = image.resize(
                    (width, round(image.height * width / image.width)),
                    Image.Resampling.LANCZOS,
                )
                reduced_path = OUTPUT / f"progress-{kind}-{width}.png"
                resized.save(reduced_path, format="PNG", optimize=True, compress_level=9)
                output.append(reduced_path)
    return output


if __name__ == "__main__":
    for item in generate():
        print(f"{item} ({item.stat().st_size} bytes)")
