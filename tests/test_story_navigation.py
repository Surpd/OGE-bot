"""Story menus and continuous rotation through the real Telegram dispatcher."""

import json
import os
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from test_companion_qa import Harness, config

from app.adaptive.session import Session
from app.bot.adaptive import _story_slots, problem_data, story_families
from app.companion.storage import open_storage
from app.persistence.rotation_history import story_family_recency
from app.persistence.scenario_repository import ScenarioPostgresRepository


async def _ignore(_: str) -> None:
    pass


async def exercise_story_navigation(
    h: Harness,
    mark: Callable[[str], Awaitable[None]] = _ignore,
) -> None:
    session = Session(h.repository, 42)

    async def open_numbers() -> None:
        await h.message("/start")
        await h.click("nav:trainings")
        await h.click("train:areas")

    def buttons(action: str) -> dict[str, str]:
        message, _ = h.button(action)
        return {
            b.callback_data.partition("~")[0]: b.text
            for row in message.reply_markup.inline_keyboard
            for b in row
            if b.callback_data
        }

    await open_numbers()
    for number in range(1, 6):
        await h.click(f"train:area:{number}")
        controls = buttons(f"train:number:{number}")
        assert set(controls) == {
            f"train:number:{number}",
            "train:areas",
            *(f"train:story:{number}:{story}" for story in story_families(number)),
        }
        assert controls[f"train:number:{number}"] == f"Весь №{number}"
        assert await session.current() is None
        await mark(f"number-{number}")
        await h.click("train:areas")

    await h.click("train:area:6")
    controls = buttons("train:number:6")
    assert any(action.startswith("train:family:") for action in controls)
    assert not any(action.startswith("train:story:") for action in controls)
    await mark("number-6-unchanged")
    await h.click("train:areas")
    await h.click("train:area:3")
    await h.click("train:story:3:STOVE")
    stove = story_families(3)["STOVE"]
    assert set(buttons("train:story-all:3:STOVE")) == {
        "train:story-all:3:STOVE",
        "train:area:3",
        *(f"train:family:{family}" for family in stove),
    }
    assert await session.current() is None
    await mark("stove-types")
    await h.click("train:area:3")
    await h.click("train:story:3:PAPER")
    data = await session.current()
    assert data["strategy"] == "family"
    assert problem_data(data)["family_id"] == story_families(3)["PAPER"][0]
    await mark("paper-direct")
    await h.click(f"ad:menu:{data['problem']}")
    await h.click("nav:trainings")
    await h.click("train:areas")
    await h.click("train:area:3")
    await h.click("train:story:3:STOVE")
    await h.click("train:story-all:3:STOVE")
    assert (await session.current())["id"] == data["id"]
    await mark("story-switch")
    await h.click("train:x:s:3:STOVE")
    active = await session.current()
    assert active["id"] != data["id"]
    assert json.loads(active["scope"])["story"] == "STOVE"
    await mark("story-all-issued")
    await h.click(f"ad:menu:{active['problem']}")
    await h.click("nav:resume")
    assert (await session.current())["problem"] == active["problem"]
    await mark("story-resume")
    scoped = []
    for position in range(6):
        current = await session.current()
        assert current["position"] == position
        family = problem_data(current)["family_id"]
        assert family in stove
        scoped.append(family)
        if position == 5:
            break
        await h.click(f"ad:skip:{current['problem']}")
        if position == 4:
            await mark("story-checkpoint")
        action = "continue" if position == 4 else "next"
        await h.click(f"ad:{action}:{current['problem']}")
    assert set(scoped[: len(stove)]) == set(stove)
    assert scoped[0] == scoped[len(stove)]
    await mark("story-next-block")
    await h.click(f"ad:finish:{current['problem']}")

    await open_numbers()
    await h.click("train:area:3")
    await h.click("train:story:3:STOVE")
    floor = "STOVE-F04-FLOOR-AREA"
    await h.click(f"train:family:{floor}")
    active = await session.current()
    assert problem_data(active)["family_id"] == floor
    await mark("stove-explicit-family")
    await h.click(f"ad:finish:{active['problem']}")

    await open_numbers()
    await h.click("train:area:3")
    await h.click("train:number:3")
    seen = []
    for position in range(12):
        current = await session.current()
        problem = problem_data(current)
        assert current["position"] == position and problem["number"] == 3
        seen.append(problem["story_code"])
        if position == 0:
            await mark("whole-number-issued")
        if position == 11:
            break
        await h.click(f"ad:skip:{current['problem']}")
        action = "continue" if (position + 1) % 5 == 0 else "next"
        await h.click(f"ad:{action}:{current['problem']}")
    assert set(seen[:6]) == set(seen[6:]) == set(story_families(3))
    assert seen[:6] == seen[6:]
    recency = await story_family_recency(h.repository, 42, 3)
    assert {family.partition("-")[0] for family in recency} == set(story_families(3))
    assert await story_family_recency(h.repository, 43, 3) == []
    await mark("whole-number-rotation")


async def test_story_picker_and_scoped_continuous_practice_through_dispatcher():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("requires PostgreSQL")
    repo = await open_storage(url, 680_000_000 + int(uuid4().hex[:8], 16))
    h = Harness(
        repo,
        config(oge_companion_adaptive_enabled=True),
        ScenarioPostgresRepository(repo._pool),
    )
    try:
        await h.message("/start")
        await h.click("exit")
        await exercise_story_navigation(h)
    finally:
        await h.bot.session.close()
        await repo._pool.close()


def test_story_recency_does_not_weight_the_larger_catalogue():
    groups = story_families(3)
    assert len(groups["STOVE"]) > len(groups["PAPER"])
    slots = _story_slots(3, story=None, recent=[], excluded=[], size=60, seed="qa")
    stories = [family.partition("-")[0] for family in slots]
    for index in range(0, len(stories), len(groups)):
        assert set(stories[index : index + len(groups)]) == set(groups)
