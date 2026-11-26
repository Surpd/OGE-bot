"""Capture Bot API payloads from the story navigation integration path."""

import asyncio
import json

from live_training_acceptance import ROOT, run_with_synthetic_user, serialize
from test_story_navigation import exercise_story_navigation

OUT = ROOT / "reports" / "navigation-rotation" / "stories"


async def exercise(harness):
    cursor = len(harness.transport.calls)
    OUT.mkdir(parents=True, exist_ok=True)

    async def mark(case: str) -> None:
        nonlocal cursor
        calls = [
            await serialize(harness.transport, harness.bot, method, out=OUT)
            for method in harness.transport.calls[cursor:]
        ]
        cursor = len(harness.transport.calls)
        assert calls
        (OUT / f"{case}.json").write_text(
            json.dumps({"case": case, "calls": calls}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    await exercise_story_navigation(harness, mark)


if __name__ == "__main__":
    asyncio.run(run_with_synthetic_user(exercise))
