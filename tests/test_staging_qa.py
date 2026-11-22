"""Offline Telegram + an isolated PostgreSQL database; no live phone/model calls."""

import copy
import json
import os
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User
from test_inline_dispatcher_postgres import TelegramSession

from app.bot.router import build_router
from app.config import Settings
from app.main import _run_schema_migrations
from app.part2_grading import available, open_client
from app.persistence.part2_bank import import_bank
from app.persistence.repository import MemoryRepository, PostgresRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository
from app.staging.catalog import fixture, generate, identity
from app.staging.middleware import StagingMiddleware, allowed_payload
from app.staging.safety import validate_database, validate_settings


def config(**changes):
    return Settings(
        _env_file=None,
        **{
            "app_env": "staging",
            "staging_owner_id": 42,
            "staging_bot_id": 123456,
            "staging_production_bot_id": 654321,
            "staging_hostname": "qa.example.invalid",
            "staging_production_hostname": "prod.example.invalid",
            "staging_release_sha": "a" * 40,
            "telegram_bot_token": "123456:TEST",
            "telegram_webhook_secret": "synthetic-secret",
            "webhook_base_url": "https://qa.example.invalid",
            "database_url": "postgresql://local/test",
            "oge_part2_enabled": True,
            **changes,
        },
    )


@pytest.mark.parametrize(
    "change",
    [
        {"staging_owner_id": None},
        {"staging_bot_id": 654321},
        {"telegram_bot_token": "654321:TEST"},
        {"staging_production_bot_id": None},
        {"staging_hostname": "prod.example.invalid"},
        {
            "staging_hostname": "PROD.example.invalid",
            "webhook_base_url": "https://PROD.example.invalid",
        },
        {"webhook_base_url": "https://user:password@qa.example.invalid"},
        {"webhook_base_url": "http://qa.example.invalid"},
        {"telegram_webhook_secret": None},
        {"staging_release_sha": "b" * 40},
        {"openai_api_key": "synthetic-not-a-key"},
        {"oge_grading_enabled": True},
        {"app_env": "production"},
        {"database_url": None},
    ],
)
def test_bad_configuration_fails_closed(monkeypatch, change):
    monkeypatch.setattr("app.staging.safety.running_sha", lambda: "a" * 40)
    with pytest.raises(RuntimeError):
        validate_settings(config(**change))


def test_correct_configuration_and_model_kill_switch(monkeypatch):
    monkeypatch.setattr("app.staging.safety.running_sha", lambda: "a" * 40)
    validate_settings(config())
    compromised = config(oge_grading_enabled=True, openai_api_key="synthetic-not-a-key")
    assert not available(compromised)
    with pytest.raises(RuntimeError, match="forbidden"):
        open_client(compromised)


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
        self.dispatcher.update.outer_middleware(StagingMiddleware(settings))
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
                    "SELECT payload FROM staging.qa_sessions WHERE owner=42"
                )
            )
        return copy.deepcopy(self.repository._staging_states[42])

    def text(self):
        return "\n".join(m.text or m.caption or "" for m in self.transport.messages.values())


@pytest.fixture
async def harness(monkeypatch):
    settings = config()
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2_check.get_settings", lambda: settings)
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
        pytest.skip("requires isolated PostgreSQL with CREATE DATABASE")
    base = os.environ["DATABASE_URL"]
    admin = await asyncpg.connect(base)
    database = "qa_staging_" + uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    url = urlsplit(base)
    local = urlunsplit((url.scheme, url.netloc, "/" + database, url.query, ""))
    settings = config(database_url=local)
    monkeypatch.setattr("scripts.init_staging.get_settings", lambda: settings)
    monkeypatch.setattr("app.staging.safety.running_sha", lambda: "a" * 40)
    monkeypatch.setenv("STAGING_INIT_EMPTY_DATABASE", "yes")
    from scripts.init_staging import main

    pool = None
    try:
        await main()
        with pytest.raises(RuntimeError, match="nonempty"):
            await main()
        pool = await asyncpg.create_pool(local, min_size=1, max_size=5)
        await _run_schema_migrations(pool)
        async with pool.acquire() as conn:
            await import_bank(conn)
        yield pool, settings
    finally:
        if pool:
            await pool.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()


async def test_postgres_restart_isolation_history_and_clean_student(staging_pool, monkeypatch):
    pool, settings = staging_pool
    await validate_database(pool, settings)
    with pytest.raises(RuntimeError):
        await validate_database(pool, config(staging_owner_id=43))
    with pytest.raises(RuntimeError):
        await validate_database(pool, Settings(_env_file=None))
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2_check.get_settings", lambda: settings)
    repo = PostgresRepository(pool)
    h = Harness(repo, settings, ScenarioPostgresRepository(pool))
    try:
        await exercise(h)
        # Clean mode uses the original dispatcher, generation, issuance and navigation.
        await h.message("№6 · Вычисления")
        before = await repo.task6_state(42)
        assert before["problem"]

        async def ordinary_dump():
            tables = await pool.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
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
        h.repository = PostgresRepository(pool)
        h.dispatcher = Dispatcher()
        h.dispatcher.update.outer_middleware(StagingMiddleware(settings))
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


@pytest.mark.parametrize("number", range(6, 20))
def test_every_number_uses_its_existing_family_and_version(number):
    from app.persistence.rotation_history import enabled

    family = enabled(number)[0]
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

    pool, settings = staging_pool
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2.get_settings", lambda: settings)
    monkeypatch.setattr("app.bot.part2_check.get_settings", lambda: settings)
    repo = PostgresRepository(pool)
    h = Harness(repo, settings, ScenarioPostgresRepository(pool))
    bank = Part2Training(pool)
    try:
        await h.message("/start")
        await h.click("exit")
        issue = await bank.open(42, 20)
        row = await bank.current(42, issue)
        message = await h.message("/start")
        await part2.render(message.as_(h.bot), repo, 42, row)
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
