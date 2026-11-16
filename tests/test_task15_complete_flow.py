from unittest.mock import AsyncMock

from aiogram.types import User

from app.bot import router
from app.math.oge15_complete import ALL_FAMILIES
from app.math.oge15_triangles import from_snapshot
from app.persistence.repository import MemoryRepository
from tests.test_task18_flow import message


async def test_public_menu_cycles_all_22_families_with_saved_png_and_answers():
    repo = MemoryRepository()
    menu = message()
    await router.choose_number(menu, repo)
    keyboard = menu.answer.await_args.kwargs["reply_markup"].inline_keyboard
    assert any("№15" in b.text for row in keyboard for b in row)
    opened = message()
    await router.choose_task15(opened, repo)
    visited = set()
    prompt_id = 101
    for _ in ALL_FAMILIES:
        saved = await repo.task15_state(42)
        s = saved["problem"]
        visited.add(s["family_id"])
        if "png_base64" in s:
            assert opened.answer_photo.await_args.args[0].data == from_snapshot(s).png_bytes
        else:
            opened.answer_photo.assert_not_awaited()
        answer = message(s["correct_answer"], prompt_id + 1)
        await router.task15_answer(answer, repo)
        assert (await repo.task15_state(42))["state"]["status"] == "solved"
        cb = AsyncMock()
        cb.data = f"t15:next:{s['problem_id']}"
        cb.from_user = User(id=42, is_bot=False, first_name="Student")
        cb.message = message(mid=answer.message_id + 1)
        await router.task15_callback(cb, repo)
        prompt_id = answer.message_id + 2
        opened = cb.message
    assert visited == set(ALL_FAMILIES)


async def test_old_text_only_session_resumes_with_original_snapshot():
    from app.math.oge15_triangles import generate

    repo = MemoryRepository()
    old = generate("OGE15-F11", 42).to_snapshot()
    await repo.ensure_task15_session(42)
    await repo.advance_task15_problem(42, None, [old])
    await repo.save_user_state(42, "task15")
    await repo.set_task15_condition_message(42, old["problem_id"], 101)
    await repo.save_user_state(42, "main_menu")
    resumed = message(mid=105)
    await router.continue_session(resumed, repo)
    resumed.answer_photo.assert_not_awaited()
    assert (await repo.task15_state(42))["problem"] == old


async def test_corrupt_task15_message_names_the_correct_exam_number():
    repo = MemoryRepository()
    opened = message()
    await router.choose_task15(opened, repo)
    saved = await repo.task15_state(42)
    saved["problem"]["correct_answer"] = "broken"
    incoming = message("0", 102)
    await router.task15_answer(incoming, repo)
    text = incoming.answer.await_args.args[0]
    assert "№15" in text and "№18" not in text
    assert (await repo.task15_state(42))["state"]["attempts"] == 0


async def test_existing_family_selection_routes_to_the_selected_graphical_type():
    from app.bot.family_selection import family_keyboard

    keyboard = family_keyboard(15)
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert len(labels) == 24  # All types, 22 families, back.
    assert not any(label.startswith("OGE15-") for label in labels)
    repo = MemoryRepository()
    await repo.set_training_family(42, 15, "OGE15-F22")
    opened = message()
    await router.choose_task15(opened, repo)
    snapshot = (await repo.task15_state(42))["problem"]
    assert snapshot["family_id"] == "OGE15-F22"
    assert opened.answer_photo.await_args.args[0].data == from_snapshot(snapshot).png_bytes
