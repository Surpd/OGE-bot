"""Offline Telegram + an isolated PostgreSQL database; no live phone/model calls."""

import copy
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User
from test_inline_dispatcher_postgres import TelegramSession

from app.bot.router import build_router
from app.companion.catalog import fixture, generate, identity
from app.companion.middleware import CompanionMiddleware, allowed_payload
from app.companion.storage import open_storage
from app.config import Settings, test_settings
from app.part2_grading import available, open_client
from app.persistence.repository import MemoryRepository, PostgresRepository
from app.persistence.rotation_history import enabled
from app.persistence.scenario_repository import ScenarioPostgresRepository


def config(**changes):
    return Settings(
        _env_file=None,
        **{
            "telegram_test_owner_ids": "42",
            "oge_part2_enabled": True,
            **changes,
        },
    )


def test_context_model_kill_switch():
    compromised = config(oge_grading_enabled=True, openai_api_key="synthetic-not-a-key")
    assert available(compromised)
    token = test_settings.set(compromised)
    try:
        assert not available(compromised)
        with pytest.raises(RuntimeError, match="forbidden"):
            open_client(compromised)
    finally:
        test_settings.reset(token)
    assert available(compromised)


@pytest.mark.parametrize("kind", ["message", "callback_query", "widget_query"])
@pytest.mark.parametrize("mutation", ["stranger", "group", "foreign_chat", "forward", "inline"])
def test_all_entry_points_enforce_owner_and_private_chat(kind, mutation):
    origin = {"chat": {"id": 42, "type": "private"}}
    event = (
        {"from": {"id": 42}, **origin}
        if kind != "callback_query"
        else {
            "from": {"id": 42},
            "message": origin,
        }
    )
    payload = {kind: event}
    assert allowed_payload(payload, 42)
    target = event.get("message", event)
    if mutation == "stranger":
        event["from"]["id"] = 43
    elif mutation == "group":
        target["chat"]["type"] = "group"
    elif mutation == "foreign_chat":
        target["chat"]["id"] = 43
    elif mutation == "forward":
        target["forward_origin"] = {"type": "user"}
    else:
        event["inline_message_id"] = "synthetic"
    assert not allowed_payload(payload, 42)


def test_frozen_regressions_and_seed_contract():
    stove, geometry = fixture(0), fixture(1)
    assert stove["snapshot"]["condition"].endswith("23, 12, 20.")
    assert "Эквивалент" in stove["note"]
    assert "90°" in geometry["snapshot"]["condition"]
    assert "НЕ зелёная" in geometry["note"]
    assert geometry["snapshot"] == generate(16, "OGE16-D01", 19, "oge16-circles-3")["snapshot"]
    assert identity(stove) == identity(json.loads(json.dumps(stove)))
    with pytest.raises(ValueError):
        generate(1, "STOVE", 155, "unknown-version")
    with pytest.raises(ValueError):
        generate(19, "OGE19-MIXED", 19, "oge19-triples-5")


class Harness:
    def __init__(self, repository, settings, scenario=None):
        self.repository = repository
        self.transport = TelegramSession()
        self.bot = Bot("123456:TEST", session=self.transport)
        self.dispatcher = Dispatcher()
        self.dispatcher.update.outer_middleware(
            CompanionMiddleware(settings, frozenset({42}), "a" * 40)
        )
        self.dispatcher.include_router(build_router())
        self.scenario = scenario
        self.counter = 0

    async def feed(self, **event):
        self.counter += 1
        await self.dispatcher.feed_update(
            self.bot,
            Update(update_id=self.counter, **event),
            repository=self.repository,
            oge15_repository=self.scenario,
        )
        assert all(
            c.__api_method__ not in {"getFile", "sendMediaGroup"} for c in self.transport.calls
        )

    async def message(self, text=None, *, owner=42, reply=None, photo=False, album=None, mid=None):
        mid = mid or self.transport.next_message_id + 10
        self.transport.next_message_id = max(self.transport.next_message_id, mid + 1)
        message = Message(
            message_id=mid,
            date=datetime.now(UTC),
            chat=Chat(id=owner, type="private"),
            from_user=User(id=owner, is_bot=False, first_name="Synthetic"),
            text=text,
            reply_to_message=reply,
            media_group_id=album,
            photo=[
                PhotoSize(
                    file_id="never-download",
                    file_unique_id="synthetic",
                    width=10,
                    height=10,
                    file_size=200,
                )
            ]
            if photo
            else None,
        )
        await self.feed(message=message)
        return message

    def button(self, action):
        for message in reversed(list(self.transport.messages.values())):
            if not message.reply_markup:
                continue
            for row in message.reply_markup.inline_keyboard:
                for b in row:
                    if b.callback_data and (
                        b.callback_data.endswith(":" + action)
                        or b.callback_data.partition("~")[0] == action
                    ):
                        return message, b.callback_data
        raise AssertionError(f"Missing button {action}")

    async def click(self, action=None, *, saved=None, owner=42):
        message, value = saved or self.button(action)
        await self.feed(
            callback_query=CallbackQuery(
                id=str(uuid4()),
                from_user=User(id=owner, is_bot=False, first_name="Synthetic"),
                chat_instance="synthetic",
                data=value,
                message=message,
            )
        )
        return message, value

    async def state(self):
        if isinstance(self.repository, PostgresRepository):
            return json.loads(
                await self.repository._pool.fetchval(
                    "SELECT payload FROM qa_sessions WHERE owner=42"
                )
            )
        return copy.deepcopy(self.repository._staging_states[42])

    def text(self):
        return "\n".join(m.text or m.caption or "" for m in self.transport.messages.values())


@pytest.fixture
async def harness(monkeypatch):
    settings = config()
    h = Harness(MemoryRepository(), settings)
    yield h
    await h.bot.session.close()


async def exercise(h):
    await h.message("/start", owner=43)
    assert not h.transport.calls
    await h.message("/start")
    entry = h.button("fixture:1")
    await h.click(saved=entry, owner=43)
    assert "card" not in await h.state()
    await h.click(saved=entry)
    original = await h.state()
    assert original["card"] == fixture(1)
    await h.click(saved=entry)  # Claimed entry keyboard cannot issue twice.
    assert (await h.state())["source_id"] == original["source_id"]
    prompt = h.transport.messages[original["replay"]["prompt_message_id"]]
    await h.message("not-a-number")
    assert (await h.state())["replay"]["attempt_count"] == 0
    answer_message = await h.message("1", reply=prompt)
    await h.feed(message=answer_message)
    assert (await h.state())["replay"]["attempt_count"] == 1
    await h.click("hint")
    assert (await h.state())["replay"]["prompt_message_id"] == prompt.message_id
    await h.message("2", reply=prompt)
    assert (await h.state())["replay"]["status"] == "failed"
    await h.click("mistake")
    assert (await h.state())["card"] == original["card"]
    assert (await h.state())["replay"]["attempt_count"] == 0
    await h.message("90", reply=prompt)  # Reply to pre-repeat condition is stale.
    assert (await h.state())["replay"]["attempt_count"] == 0
    await h.message("90")
    assert (await h.state())["replay"]["status"] == "solved"
    assert "НЕ зелёная приёмка" in h.text()
    await h.click("home")
    await h.click("id")
    await h.message(original["card_id"])
    assert (await h.state())["card"] == original["card"]
    await h.click("next")
    assert (await h.state())["card"] == fixture(2)
    await h.click("display:png")
    assert any(c.__api_method__ == "sendPhoto" for c in h.transport.calls)
    await h.click("solution")
    await h.click("next")
    photo_state = await h.state()
    assert photo_state["card"]["number"] == 20
    photo_prompt = h.transport.messages[photo_state["replay"]["prompt_message_id"]]
    await h.message(photo=True, reply=prompt)
    assert not (await h.state())["photo"]
    await h.message(photo=True, reply=photo_prompt, album="synthetic-album")
    assert not (await h.state())["photo"]
    await h.message(photo=True, reply=photo_prompt)
    assert (await h.state())["photo"]
    await h.click("photo:ok")
    await h.click("photo:error")
    assert "ИМИТАЦИЯ · Ошибка" in h.text()
    assert "never-download" not in json.dumps(await h.state())
    await h.click("remove")
    assert not (await h.state())["photo"]
    old = h.button("repeat")
    await h.click("exit")
    assert not (await h.state())["active"]
    await h.click(saved=old)
    assert not (await h.state())["active"]


async def test_complete_offline_dispatcher_route(harness):
    await exercise(harness)


async def test_catalog_and_wrong_seed_never_substitute(harness):
    h = harness
    await h.message("/start")
    await h.click("numbers")
    await h.click("number:16:0")
    await h.click("choose:0")
    await h.click("seed")
    await h.message("19 nonexistent")
    assert "card" not in await h.state()
    assert "Похожая задача не подставлена" in h.text()
    await h.click("home")
    await h.click("fixture:0")
    original = (await h.state())["card"]
    await h.click("repeat")
    assert (await h.state())["card"] == original
    await h.click("home")
    await h.click("numbers")
    await h.click("number:25:0")
    await h.click("choose:0")
    assert (await h.state())["card"]["number"] == 25


async def test_delivery_rejection_fallback_and_uncertain_send(harness, monkeypatch):
    h = harness
    await h.message("/start")
    original_request = h.transport.make_request
    rich_rejections = 0

    async def reject_rich(bot, method, timeout=None):  # noqa: ASYNC109
        nonlocal rich_rejections
        if method.__api_method__ == "sendRichMessage":
            rich_rejections += 1
            raise TelegramBadRequest(
                method=method, message="Bad Request: can't parse entities: unsupported start tag"
            )
        return await original_request(bot, method, timeout)

    monkeypatch.setattr(h.transport, "make_request", reject_rich)
    await h.click("fixture:2")
    assert rich_rejections
    assert any(c.__api_method__ == "sendPhoto" for c in h.transport.calls)
    exact = (await h.state())["card"]
    old = h.button("repeat")

    async def uncertain(bot, method, timeout=None):  # noqa: ASYNC109
        if method.__api_method__ in {"sendPhoto", "sendRichMessage"}:
            raise TelegramNetworkError(method=method, message="synthetic timeout")
        return await original_request(bot, method, timeout)

    monkeypatch.setattr(h.transport, "make_request", uncertain)
    from app.bot.presentation import MathDeliveryUncertain

    with pytest.raises(MathDeliveryUncertain):
        await h.click(saved=old)
    assert (await h.state())["card"] == exact
    source_id = (await h.state())["source_id"]
    await h.click(saved=old)
    assert (await h.state())["source_id"] == source_id


@pytest.fixture
async def staging_pool(monkeypatch):
    if not os.getenv("DATABASE_URL"):
        pytest.skip("requires isolated PostgreSQL")
    url = os.environ["DATABASE_URL"]
    bot_id = 100000000 + int(uuid4().hex[:7], 16)
    repo = await open_storage(url, bot_id)
    pool = repo._pool
    settings = config(database_url=url)
    try:
        yield pool, settings, repo
    finally:
        await pool.close()
        conn = await asyncpg.connect(url)
        await conn.execute(f'DROP SCHEMA "{repo.schema}" CASCADE')
        await conn.close()


async def test_postgres_restart_isolation_history_and_clean_student(staging_pool, monkeypatch):
    pool, settings, repo = staging_pool
    h = Harness(repo, settings, ScenarioPostgresRepository(pool))
    try:
        await exercise(h)
        # Clean mode uses the original dispatcher, generation, issuance and navigation.
        await h.message("№6 · Вычисления")
        before = await repo.task6_state(42)
        assert before["problem"]

        async def ordinary_dump():
            tables = await pool.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() "
                "AND tablename<>'qa_sessions'"
            )
            return {
                r["tablename"]: await pool.fetchval(
                    f"SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]') FROM \"{r['tablename']}\" t"
                )
                for r in tables
            }

        baseline = await ordinary_dump()
        await h.message("/qa")
        await h.click("history:0")
        await h.click("history_open:0")
        assert (await h.state())["card"]["snapshot"]["problem_id"] == before["problem"][
            "problem_id"
        ]
        await h.click("solution")
        await h.click("repeat")
        exact = (await h.state())["card"]
        # A fresh repository/middleware instance restores the exact pinned card.
        h.repository = type(repo)(pool, repo.schema)
        h.dispatcher = Dispatcher()
        h.dispatcher.update.outer_middleware(
            CompanionMiddleware(settings, frozenset({42}), "a" * 40)
        )
        h.dispatcher.include_router(build_router())
        await h.click("repeat")
        assert (await h.state())["card"] == exact
        assert await ordinary_dump() == baseline  # incl. budgets, errors, preferences, sessions
        await h.click("exit")
        after = await repo.task6_state(42)
        assert after["problem"]["problem_id"] == before["problem"]["problem_id"]
        assert after["state"]["attempts"] == before["state"]["attempts"]
    finally:
        await h.bot.session.close()


@pytest.mark.parametrize(
    "number,family", [(number, family) for number in range(6, 20) for family in enabled(number)]
)
def test_every_number_uses_its_existing_family_and_version(number, family):
    card = generate(number, family)
    snapshot = card["snapshot"]
    assert snapshot["family_id"] == family
    assert snapshot["generator_version"]
    if number != 19:
        restored = generate(number, family, snapshot["seed"], snapshot["generator_version"])
        assert restored["snapshot"] == snapshot


async def test_clean_student_photo_uses_real_upload_flow_but_no_model(staging_pool, monkeypatch):
    from app.bot import part2
    from app.persistence.part2_training import Part2Training

    pool, settings, repo = staging_pool
    h = Harness(repo, settings, ScenarioPostgresRepository(pool))
    bank = Part2Training(pool)
    try:
        await h.message("/start")
        await h.click("exit")
        issue = await bank.open(42, 20)
        row = await bank.current(42, issue)
        message = await h.message("hello")
        token = test_settings.set(settings)
        try:
            await part2.render(message.as_(h.bot), repo, 42, row)
        finally:
            test_settings.reset(token)
        row = await bank.current(42)
        prompt = h.transport.messages[row["prompt_message_id"]]
        await h.message(photo=True, reply=prompt)
        row = await bank.current(42)
        assert row["draft"] and row["photo_message"]
        await h.click(part2.photo_action("check", row))
        assert "ИМИТАЦИЯ · Пример результата" in h.text()
        assert not await pool.fetchval("SELECT count(*) FROM part2_grades")
        assert not await pool.fetchval("SELECT count(*) FROM part2_api_tests")
        assert not (await bank.current(42))["scored"]
        assert all(c.__api_method__ != "getFile" for c in h.transport.calls)
    finally:
        await h.bot.session.close()


async def test_simulated_grade_png_rejection_delivers_plain_once(harness, monkeypatch):
    h = harness
    await h.message("/start")
    await h.click("fixture:3")
    await h.click("display:png")
    state = await h.state()
    await h.message(photo=True, reply=h.transport.messages[state["replay"]["prompt_message_id"]])
    original_request = h.transport.make_request
    failures = []

    async def reject_png(bot, method, timeout=None):  # noqa: ASYNC109
        if method.__api_method__ == "sendPhoto":
            failures.append(method)
            raise TelegramBadRequest(method=method, message="PHOTO_INVALID_DIMENSIONS")
        return await original_request(bot, method, timeout)

    monkeypatch.setattr(h.transport, "make_request", reject_png)
    await h.click("photo:ok")
    assert len(failures) == 1
    assert "ИМИТАЦИЯ · Пример результата" in h.text()
    monkeypatch.setattr(h.transport, "make_request", original_request)
    await h.click("remove")
    assert not (await h.state())["photo"]


async def test_phone_search_archive_diagnostics_and_first_five(harness):
    h = harness
    await h.message("/start")
    await h.click("fixture:0")
    exact = (await h.state())["card"]
    for position in (2, 3, 4, 5, 1):
        await h.click(f"position:{position}")
        current = (await h.state())["card"]
        assert current["number"] == position
        assert current["scenario"] == exact["scenario"]
    await h.click("diagnostic")
    assert "SHA=" + "a" * 40 in h.text()
    assert "step=position:1" in h.text()
    await h.click("home")
    await h.click("archive")
    await h.click("arch:" + identity(exact))
    assert (await h.state())["card"] == exact
    await h.click("home")
    await h.click("id")
    await h.message("438301")
    assert (await h.state())["card"]["snapshot"]["task_id"] == "oge-part2-reshu-438301"
    await h.click("exit")
    await h.message("🔬 Проверки")
    assert (await h.state())["active"]


async def test_reset_only_test_owner_and_preserves_exact_archive(staging_pool):
    pool, settings, repo = staging_pool
    h = Harness(repo, settings, ScenarioPostgresRepository(pool))
    try:
        await pool.execute("INSERT INTO users(telegram_user_id) VALUES(43)")
        await h.message("/start")
        await h.click("fixture:0")
        exact = (await h.state())["card"]
        await h.click("exit")
        await h.message("№6 · Вычисления")
        assert (await repo.task6_state(42))["problem"]
        await h.message("🔬 Проверки")
        await h.click("reset")
        old = h.button("reset_confirm")
        await h.click("reset_confirm")
        assert not await pool.fetchval("SELECT count(*) FROM users WHERE telegram_user_id=42")
        assert await pool.fetchval("SELECT count(*) FROM users WHERE telegram_user_id=43") == 1
        assert not await pool.fetchval("SELECT count(*) FROM part2_grades")
        await h.click(saved=old)
        await h.click("archive")
        await h.click("arch:" + identity(exact))
        assert (await h.state())["card"] == exact
    finally:
        await h.bot.session.close()
