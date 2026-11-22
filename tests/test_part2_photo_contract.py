"""Shared offline photo contract for all six written-response numbers."""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import SecretStr

from app.bot import part2, part2_check, part2_progress
from app.config import Settings
from app.part2_grading import Assessment, Grade
from app.persistence.part2_grades import reserve
from app.persistence.part2_insights import history
from app.persistence.part2_training import Part2Training
from app.persistence.repository import PostgresRepository


@pytest.mark.parametrize("number", range(20, 26))
@pytest.mark.parametrize("outcome", [2, 0, "unreadable", "timeout"])
async def test_photo_contract(bank_pool, monkeypatch, number, outcome):
    bank = Part2Training(bank_pool)
    repo = PostgresRepository(bank_pool)
    await repo.save_user_state(1, "part2")
    await bank_pool.execute(
        "UPDATE part2_versions SET available=(task_id=$1)",
        f"oge-part2-fipi-demo-2027-{number}",
    )
    issue = await bank.open(1, number)
    await bank.bind_prompt(1, issue, 10)
    monkeypatch.setattr(part2, "store", lambda _: bank)
    monkeypatch.setattr(part2_progress, "store", lambda _: bank)
    delivery = AsyncMock(return_value=SimpleNamespace(message_id=10))
    monkeypatch.setattr(part2, "send_text", delivery)
    monkeypatch.setattr(part2_check, "send_text", delivery)
    monkeypatch.setattr(part2_progress, "send_text", delivery)
    settings = Settings(_env_file=None, oge_grading_enabled=True, openai_api_key=SecretStr("mock"))
    monkeypatch.setattr(part2_check, "get_settings", lambda: settings)
    stream = BytesIO()
    Image.new("RGB", (100, 100), "white").save(stream, format="JPEG")
    raw = stream.getvalue()
    bot = SimpleNamespace(
        get_file=AsyncMock(
            return_value=SimpleNamespace(file_size=len(raw), file_path="synthetic.jpg")
        )
    )

    async def download(_path, *, destination):
        destination.write(raw)

    bot.download_file = download
    response = AsyncMock()

    def photo(mid, reply=10, album=None):
        return SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=SimpleNamespace(id=1),
            bot=bot,
            message_id=mid,
            caption=None,
            media_group_id=album,
            photo=[SimpleNamespace(file_id=f"photo-{mid}", file_size=len(raw))],
            reply_to_message=SimpleNamespace(message_id=reply, photo=None) if reply else None,
            answer=response,
            answer_photo=AsyncMock(),
        )

    msg = photo(100)
    # Neither unbound photos, stale replies nor either album page enter the draft.
    for rejected in (
        photo(90, reply=None),
        photo(91, reply=9),
        photo(92, album="a"),
        photo(93, album="a"),
    ):
        await part2.collect(rejected, repo)
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_work") == 0
    await part2.collect(msg, repo)
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0
    row = await bank.current(1)
    assert row["photo_message"] == 100 and row["revision"] == 1
    markup = delivery.call_args.kwargs["reply_markup"]
    assert [b.text for r in markup.inline_keyboard for b in r] == [
        "Проверить решение",
        "Убрать фото",
    ]
    check_button, remove_button = [b.callback_data for r in markup.inline_keyboard for b in r]
    assert f"№{number}" in delivery.call_args.args[2]
    await part2.collect(msg, repo)  # Telegram redelivery is not a new photo.
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_work") == 1
    # Remove just the selected attachment; no revision charge or task closure.
    await part2.action(msg, repo, 1, remove_button)
    assert (await bank.current(1))["revision"] == 1
    assert not (await bank.current(1))["draft"]
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0
    # resume() above sends a condition through mocked transport: pin its synthetic ID.
    await bank.bind_prompt(1, issue, 10)
    await part2.collect(photo(101), repo)
    fresh = await bank.current(1)
    fresh_button = part2.photo_action("check", fresh)
    await part2.action(msg, repo, 1, remove_button)
    await part2.action(msg, repo, 1, check_button)
    assert (await bank.current(1))["photo_message"] == 101
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0

    @asynccontextmanager
    async def client(_):
        yield object()

    monkeypatch.setattr(part2_check, "open_client", client)
    monkeypatch.setattr(part2_check, "check_size", AsyncMock())
    calls = []

    async def assess(*_):
        assert any(c.args == ("Проверяю решение…",) for c in response.await_args_list)
        calls.append(1)
        await asyncio.sleep(0)
        if outcome == "timeout":
            raise TimeoutError
        score = outcome if isinstance(outcome, int) else None
        rule = fresh["card"]["rubric"]["levels"][str(score)]["rule"] if score is not None else ""
        assessment = Assessment(
            status="graded" if score is not None else "unreadable",
            score=score,
            max_score=2,
            needs_review=score is None,
            confidence=0.9,
            criterion_evidence=[dict(criterion=rule, student_evidence="Synthetic")] if rule else [],
            correct_steps=["Верный шаг"],
            errors=["Ошибка"],
            feedback="Синтетический результат",
            next_step="Учебный совет",
        )
        return Grade(assessment, 100, 20, "mock", Decimal("0.001"))

    monkeypatch.setattr(part2_check, "assess", assess)
    await asyncio.gather(
        part2.action(msg, repo, 1, fresh_button),
        part2.action(msg, repo, 1, fresh_button),
    )
    assert len(calls) == 1
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 1
    after = await bank.current(1)
    assert after["revision"] == 2 and not after["closed"]
    texts = [c.args[2] for c in delivery.call_args_list]
    assert any("Задача открыта." in t for t in texts)
    if isinstance(outcome, int):
        assert any(f"Оценка: {outcome} из 2" in t for t in texts)
        assert any("Проверка сохранена" in t for t in texts)
        if outcome == 2:
            assert not any("Как исправить" in t for t in texts)
    else:
        assert any("Балл не выставлен" in t or "балл не выставлен" in t for t in texts)
    # Cancel a subsequent photo, preserving earlier assessment and open issue.
    await part2.collect(photo(102), repo)
    next_row = await bank.current(1)
    await part2.action(msg, repo, 1, part2.photo_action("remove", next_row))
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 1
    assert not (await bank.current(1))["draft"]
    assert (await history(bank_pool, 1, 0))[0]["id"] == issue
    delivery.reset_mock()
    await part2_progress.page(msg, repo, 1, ["work", str(issue), "1", "0"])
    details = delivery.call_args.args[2]
    assert "Задача открыта." in details
    if outcome == 2:
        assert "Оценка: 2 из 2" in details and "Как исправить" not in details
    if isinstance(outcome, int):
        assert await bank.finish(1, issue)
        await part2_progress.page(msg, repo, 1, ["work", str(issue), "1", "0"])
        assert "Задача закрыта." in delivery.call_args.args[2]


@pytest.mark.parametrize("number", range(20, 26))
async def test_cross_card_and_atomic_attachment_identity(bank_pool, number):
    bank = Part2Training(bank_pool)
    a = await bank.open(1, number)
    await bank.bind_prompt(1, a, 10)
    assert await bank.append(1, a, 1, 100, None, "old", condition_message=10) == "saved"
    # Replace within the same revision. Old buttons must not refer to the replacement.
    assert await bank.append(1, a, 1, 101, None, "new", replace_photo=100) == "saved"
    assert not await bank.remove_photo(1, a, 1, 100)
    assert not (await reserve(bank_pool, Settings(_env_file=None), 1, a, 1, photo_message=100))[1]
    b = await bank.open(1, number)
    await bank.bind_prompt(1, b, 20)
    assert await bank.append(1, b, 1, 102, None, "wrong", condition_message=10) == "stale"
    assert await bank.append(1, a, 1, 103, None, "wrong", condition_message=10) == "stale"
    assert not await bank.remove_photo(1, a, 1, 101)
    assert not (await reserve(bank_pool, Settings(_env_file=None), 1, a, 1, photo_message=101))[1]
    assert not (await bank.current(1))["draft"]
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0


async def test_legacy_album_draft_is_not_gradeable(bank_pool):
    bank = Part2Training(bank_pool)
    issue = await bank.open(1, 25)
    await bank_pool.execute(
        """INSERT INTO part2_work(issue_id,revision,message_id,photo,media_group)
        VALUES($1,1,100,'legacy-page-1','legacy-album')""",
        issue,
    )
    notice, work = await reserve(
        bank_pool, Settings(_env_file=None), 1, issue, 1, photo_message=100
    )
    assert "Альбом нельзя проверить частично" in notice and not work
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0
    assert await bank.remove_photo(1, issue, 1, 100)
    assert await bank.append(1, issue, 1, 101, None, "complete-single-photo") == "saved"
    assert (await reserve(bank_pool, Settings(_env_file=None), 1, issue, 1, photo_message=101))[1]
