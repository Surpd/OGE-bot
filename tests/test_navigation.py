import pytest

from app.bot import menu
from app.bot.navigation import navigation_screen


def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_main_menu_only_exposes_implemented_sections():
    assert callbacks(menu.main_menu()) == ["nav:numbers", "nav:progress", "nav:display"]
    assert callbacks(menu.main_menu(has_session=True))[0] == "nav:resume"


@pytest.mark.asyncio
async def test_same_menu_message_rejects_previous_keyboard_revision():
    from app.persistence.repository import MemoryRepository

    repository = MemoryRepository()
    await repository.save_user_state(42, "main_menu")
    assert await repository.set_navigation_message(42, "main_menu", 12, "old")
    assert await repository.claim_navigation_message(42, 12, "old")
    assert await repository.set_navigation_message(42, "main_menu", 12, "new")
    assert not await repository.claim_navigation_message(42, 12, "old")
    assert not await repository.claim_navigation_message(42, 12)
    assert await repository.claim_navigation_message(42, 12, "new")


@pytest.mark.asyncio
async def test_menu_navigation_edits_existing_message_without_sending_another():
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import Chat, Message, User

    from app.bot.navigation import NavigationMessage, prepare_navigation_markup
    from app.persistence.repository import MemoryRepository

    sent = Message(message_id=12, date=datetime.now(), chat=Chat(id=42, type="private"))
    source = SimpleNamespace(edit_text=AsyncMock(return_value=sent), answer=AsyncMock())
    callback = SimpleNamespace(from_user=User(id=42, is_bot=False, first_name="Student"))
    repository = MemoryRepository()
    await repository.save_user_state(42, "main_menu")
    proxy = NavigationMessage(source, callback, repository)
    result = await proxy.answer("Меню", reply_markup=prepare_navigation_markup(menu.main_menu()))
    assert result.message_id == 12
    source.edit_text.assert_awaited_once()
    source.answer.assert_not_awaited()


def test_number_menu_is_compact_and_gated():
    basic = menu.number_menu()
    assert all(len(row) <= 2 for row in basic.inline_keyboard)
    assert "nav:task:7" not in callbacks(basic)
    full = menu.number_menu(include_task7=True, include_task11=True, include_task13=True)
    assert {f"nav:task:{n}" for n in range(6, 15)} <= set(callbacks(full))


@pytest.mark.parametrize("number", range(6, 15))
@pytest.mark.parametrize("completed", [False, True])
def test_legacy_training_menus_preserve_callback_contract(number, completed):
    markup = getattr(menu, f"task{number}_menu")("problem", completed=completed)
    actions = [value.split(":")[1] for value in callbacks(markup)]
    assert actions == (["next", "menu"] if completed else ["hint", "solution", "skip", "menu"])
    assert all(value.startswith(f"t{number}:") and value.endswith(":problem")
               for value in callbacks(markup))


def test_choices_only_available_on_active_task13():
    assert callbacks(menu.task13_menu("p", choices=True))[:4] == [
        f"t13:choose:p:{n}" for n in range(1, 5)
    ]
    assert "choose" not in ":".join(callbacks(menu.task13_menu("p", choices=True, completed=True)))


def test_navigation_screen_identification():
    assert navigation_screen(menu.main_menu()) == "main_menu"
    assert navigation_screen(menu.number_menu()) == "number_selection"
    assert navigation_screen(menu.progress_menu()) == "progress"
    assert navigation_screen(menu.task6_menu("p")) is None

@pytest.mark.asyncio
async def test_stale_navigation_never_changes_training(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import Chat, Message, User

    import app.bot
    from app.bot.navigation import navigation_callback

    target = AsyncMock()
    handlers = SimpleNamespace(
        return_to_menu=AsyncMock(), choose_number=target, continue_session=AsyncMock(),
        show_progress=AsyncMock(), show_progress_details=AsyncMock(),
    )
    monkeypatch.setattr(app.bot, "router", handlers, raising=False)
    message = Message(message_id=12, date=datetime.now(), chat=Chat(id=1, type="private"))
    callback = SimpleNamespace(
        message=message, data="nav:numbers", from_user=User(id=1, is_bot=False, first_name="x"),
        answer=AsyncMock(),
    )
    repository = SimpleNamespace(claim_navigation_message=AsyncMock(return_value=False))
    await navigation_callback(callback, repository)
    target.assert_not_awaited()
    repository.claim_navigation_message.assert_awaited_once_with(1, 12, None)


@pytest.mark.asyncio
async def test_navigation_uses_tapping_user_and_claims_once(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import Chat, Message, User

    import app.bot
    from app.bot.navigation import navigation_callback

    target = AsyncMock()
    handlers = SimpleNamespace(
        return_to_menu=AsyncMock(), choose_number=target, continue_session=AsyncMock(),
        show_progress=AsyncMock(), show_progress_details=AsyncMock(),
    )
    monkeypatch.setattr(app.bot, "router", handlers, raising=False)
    message = Message(message_id=12, date=datetime.now(), chat=Chat(id=1, type="private"),
                      from_user=User(id=99, is_bot=True, first_name="bot"))
    callback = SimpleNamespace(
        message=message, data="nav:numbers", from_user=User(id=1, is_bot=False, first_name="x"),
        answer=AsyncMock(),
    )
    repository = SimpleNamespace(claim_navigation_message=AsyncMock(side_effect=[True, False]))
    await navigation_callback(callback, repository)
    await navigation_callback(callback, repository)
    target.assert_awaited_once()
    assert target.await_args.args[0].from_user.id == 1

@pytest.mark.asyncio
async def test_start_removes_legacy_reply_keyboard_before_bound_inline_menu():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardRemove, User

    from app.bot.router import start
    from app.persistence.repository import MemoryRepository

    repository = MemoryRepository()
    message = AsyncMock()
    message.from_user = User(id=123, is_bot=False, first_name="Student")
    message.answer.side_effect = [
        SimpleNamespace(message_id=200), SimpleNamespace(message_id=201),
    ]
    await start(message, repository)
    first, last = message.answer.await_args_list
    assert isinstance(first.kwargs["reply_markup"], ReplyKeyboardRemove)
    assert isinstance(last.kwargs["reply_markup"], InlineKeyboardMarkup)
    assert "Выберите раздел" in last.args[0]
    from app.bot.navigation import navigation_revision

    revision = navigation_revision(last.kwargs["reply_markup"])
    assert await repository.claim_navigation_message(123, 201, revision)
    assert not await repository.claim_navigation_message(123, 200)
