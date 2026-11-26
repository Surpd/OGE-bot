from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot import adaptive, menu, router, scenario_training
from app.bot.family_selection import PAGE_SIZE, _selection_name, show_families
from app.bot.navigation import navigation_screen
from app.config import get_settings
from app.persistence.repository import MemoryRepository
from app.persistence.rotation_history import enabled


def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


@pytest.fixture
def written_enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oge_part2_enabled", True)


def test_visual_number_groups_follow_available_registry_and_written_flag(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oge_part2_enabled", False)
    card, markup = menu.number_card()
    from app.bot.trainings import TRAININGS

    available = [t for t in TRAININGS if t.available and t.number not in {7, 11, 13}]
    assert card.screen == "numbers"
    assert [entry.key for section in card.sections for entry in section.entries] == [
        *(str(n) for n in range(1, 6)), *(str(t.number) for t in available),
    ]
    assert callbacks(markup)[:5] == [f"nav:oge15:{n}" for n in range(1, 6)]
    assert "nav:oge15" in callbacks(markup)
    assert navigation_screen(markup) == "number_selection"
    assert not any(data.startswith("p2:") for data in callbacks(markup))
    assert not any("Вторая часть" in button.text
                   for row in markup.inline_keyboard for button in row)


def test_written_visual_uses_existing_routes_and_legacy_fallback(written_enabled):
    card, markup = menu.number_card(page=99)
    assert card.screen == "part2"
    assert [entry.key for entry in card.sections[0].entries] == [str(n) for n in range(20, 26)]
    assert set(callbacks(markup)) == {
        *(f"p2:menu:{n}" for n in range(20, 26)), "nav:numbers:0", "nav:main",
    }
    # The already-supported numbered page route still has a complete textual path.
    text, fallback = menu.number_page(page=99)
    assert "Выберите номер" in text and "nav:main" in callbacks(fallback)
    assert navigation_screen(markup) == "number_selection"


def test_short_number_card_keeps_live_practical_and_geometry_groups(written_enabled):
    numbers = sorted(set(adaptive.catalog().values()))
    card, markup = adaptive.area_card()
    assert [int(entry.key) for section in card.sections for entry in section.entries] == numbers
    assert [data for data in callbacks(markup) if data.startswith("train:area:")] == [
        f"train:area:{n}" for n in numbers
    ]
    assert "train:areas:1" in callbacks(markup)
    assert not any(data.startswith("p2:") for data in callbacks(markup))
    written, written_markup = adaptive.area_card(1)
    assert written.screen == "part2"
    assert "train:areas:0" in callbacks(written_markup)
    assert {data for data in callbacks(written_markup) if data.startswith("p2:")} == {
        f"p2:menu:{n}" for n in range(20, 26)
    }


def test_story_icons_and_types_are_taken_from_live_registry():
    for number in range(1, 6):
        groups = adaptive.story_families(number)
        card = adaptive.picker_card(number)
        assert [entry.icon for entry in card.sections[0].entries] == list(groups)
        assert [entry.label for entry in card.sections[0].entries] == [
            scenario_training.STORY_NAMES[code] for code in groups
        ]
        for story, families in groups.items():
            types = adaptive.picker_card(number, story=story)
            assert [entry.label for entry in types.sections[0].entries] == [
                adaptive.title(family) for family in families
            ]
            assert callbacks(adaptive.story_area_keyboard(number, story, families))[1:-1] == [
                f"train:family:{family}" for family in families
            ]


def test_number_type_page_order_matches_actual_family_buttons():
    for number in sorted(set(adaptive.catalog().values()) - set(range(1, 6))):
        for page in (0, 1, 99):
            card = adaptive.picker_card(number, page)
            data = callbacks(adaptive.family_area_keyboard(number, page))
            families = [value.removeprefix("train:family:") for value in data
                        if value.startswith("train:family:")]
            assert [entry.label for entry in card.sections[0].entries] == [
                adaptive.title(family) for family in families
            ]


def test_legacy_story_picker_retains_mode_routes_and_uses_available_stories(monkeypatch):
    monkeypatch.setattr(scenario_training, "public_registry", lambda: SimpleNamespace(
        available_stories=lambda mode, position=None: ("PAPER", "FLAT"),
    ))
    card = scenario_training.story_card(2)
    assert [entry.icon for entry in card.sections[0].entries] == ["PAPER", "FLAT"]
    data = callbacks(scenario_training._story_keyboard(2))
    assert data == ["oge15:story:PAPER:n2", "oge15:story:FLAT:n2",
                    "oge15:story:RANDOM:n2", "oge15:unfinished", "oge15:return:2"]
    assert "oge15:linked:PAPER" in callbacks(scenario_training._story_keyboard(linked_only=True))


@pytest.mark.asyncio
async def test_legacy_family_visual_uses_same_global_indexes_as_keyboard(monkeypatch):
    monkeypatch.setattr("app.bot.family_selection.visual_enabled", lambda *args: True)
    message = AsyncMock()
    message.from_user = User(id=123, is_bot=False, first_name="Student")
    send = AsyncMock()
    monkeypatch.setattr("app.bot.family_selection.send_text", send)
    await show_families(message, MemoryRepository(), 6, 1)
    card = send.await_args.kwargs["visual"]
    assert [entry.key for entry in card.sections[0].entries] == [
        str(i) for i in range(PAGE_SIZE + 1, min(2 * PAGE_SIZE, len(enabled(6))) + 1)
    ]
    assert [entry.label for entry in card.sections[0].entries] == [
        _selection_name(6, family) for family in enabled(6)[PAGE_SIZE:2 * PAGE_SIZE]
    ]


@pytest.mark.asyncio
async def test_number_builder_failure_keeps_original_text_and_keyboard(monkeypatch):
    monkeypatch.setattr(router, "visual_enabled", lambda *args: True)
    def broken(**kwargs):
        raise ValueError("invalid visual catalog")

    monkeypatch.setattr(menu, "number_card", broken)
    send = AsyncMock()
    monkeypatch.setattr(router, "send_text", send)
    message = AsyncMock()
    message.from_user = User(id=123, is_bot=False, first_name="Student")
    repository = MemoryRepository()
    await router.choose_number(message, repository)
    assert send.await_args.kwargs["visual"] is None
    assert send.await_args.kwargs["visual_reply_markup"] is None
    assert "Выберите номер задания" in send.await_args.args[2]
    assert navigation_screen(send.await_args.kwargs["reply_markup"]) == "number_selection"
    assert await repository.user_state(123) == "number_selection"


@pytest.mark.asyncio
async def test_disabled_visual_never_builds_alternative_number_menu(monkeypatch):
    builder = AsyncMock()
    monkeypatch.setattr(menu, "number_card", builder)
    monkeypatch.setattr(router, "visual_enabled", lambda *args: False)
    send = AsyncMock()
    monkeypatch.setattr(router, "send_text", send)
    message = AsyncMock()
    message.from_user = User(id=123, is_bot=False, first_name="Student")
    await router.choose_number(message, MemoryRepository())
    builder.assert_not_called()
    assert send.await_args.kwargs["visual"] is None
