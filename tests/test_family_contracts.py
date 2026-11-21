import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot

from app.bot.family_display import formats, typeset_family_text
from app.bot.presentation import format_rich_message, send_text
from app.math.family_cycle import ordinary_candidates
from app.math.generator import generate, training_rejection
from app.math.scheduler import build_candidate_batch
from tests.test_rich_math_runtime import incoming


def test_matrix_covers_audited_families_and_pins_unsafe_templates():
    audit = json.loads(Path("reports/family-contract-samples.json").read_text())
    assert set(formats()) == set(audit) | {"written-feedback"}
    for family, stats in audit.items():
        assert stats["variants"] > 0
        if stats["unsafe_variants"]:
            assert formats()[family] == "png"


@pytest.mark.parametrize(
    "family,transport",
    [
        ("OGE11-F08", "png"),
        ("OGE06-F006-MIXED-MINUS-DECIMAL", "rich"),
    ],
)
async def test_same_template_uses_same_bot_method(family, transport):
    bot = Bot("123456:TEST")
    bot.send_rich_message = AsyncMock()
    bot.send_photo = AsyncMock()
    repo = AsyncMock()
    repo.math_display.return_value = "auto"
    try:
        for text in ["Вычислите 2.", "Вычислите 11 1/2 - 9,3.", "Ответ: 2/7"]:
            await send_text(incoming(bot), repo, text, math_family=family)
        assert bot.send_rich_message.await_count == (3 if transport == "rich" else 0)
        assert bot.send_photo.await_count == (3 if transport == "png" else 0)
        if transport == "rich":
            html = bot.send_rich_message.await_args_list[1].kwargs["rich_message"].html
            assert r"11\frac{1}{2} - 9{,}3" in html
    finally:
        await bot.session.close()


def test_geometry_quotient_and_tyre_markings_keep_their_distinct_meanings():
    formatted = typeset_family_text("Поэтому sin B = AC / AB = 3 / 5.", "OGE15-F15")
    assert r"\frac{AC}{AB}" in format_rich_message(formatted)
    assert r"\frac{3}{5}" in format_rich_message(formatted)
    assert typeset_family_text("Шины 165/60 R18", "TYRES-DIAMETER") == "Шины 165/60 R18"


def test_prescribed_fraction_rejects_degenerate_training_but_reproduces_original():
    family = "OGE06-F009-PRESCRIBED-NUMERATOR"
    original = generate(family, 1)
    assert "8/9 - 4/9" in original.condition
    assert training_rejection(original) == "same_denominator"
    assert generate(family, 1).to_snapshot() == original.to_snapshot()
    for seed in range(24):
        batch = ordinary_candidates(
            build_candidate_batch, {"cycle_families": [family], "selected_family_id": family}, seed
        )
        for question in batch:
            replay = generate(family, question["seed"])
            assert replay.condition == question["condition"]
            assert training_rejection(replay) is None


def test_exhausted_tail_and_cycle_boundary_do_not_force_repeat():
    def available(state, seed):
        family = state["selected_family_id"]
        if family.startswith("empty"):
            return []
        return [{"family_id": family, "condition": f"{family} {seed}"}]

    state = {
        "cycle_families": ["last", "other", "empty1", "empty2"],
        "cycle_last": "last",
        "cycle_tail": ["empty1"],
    }
    for seed in range(30):
        batch = ordinary_candidates(available, state, seed)
        assert [task["family_id"] for task in batch] == ["other"]
        assert not ordinary_candidates(available, {**state, "selected_family_id": "empty1"}, seed)
        explicit = ordinary_candidates(available, {**state, "selected_family_id": "last"}, seed)
        assert explicit[0]["family_id"] == "last"
        assert explicit[0]["_family_queue_after"] == ["empty1"]
