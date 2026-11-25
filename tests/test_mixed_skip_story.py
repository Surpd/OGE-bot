"""Offline Telegram through the real random-Mix entry and shared presentation."""

import asyncio
import copy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, User
from test_inline_dispatcher_postgres import TelegramSession

from app.bot import mixed_training
from app.bot.router import build_router
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import MemoryRepository, PostgresRepository
from app.persistence.training_insights import training_insights


class Flow:
    def __init__(self, repository):
        self.repo = repository
        self.store = MixedTrainingRepository(repository)
        self.session = TelegramSession()
        self.bot = Bot("123456:SYNTHETIC", session=self.session)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(build_router())
        self.user = User(id=42, is_bot=False, first_name="Synthetic")
        self.update = 0

    async def feed(self, **event):
        from aiogram.types import Update

        self.update += 1
        await self.dispatcher.feed_update(
            self.bot,
            Update(update_id=self.update, **event),
            repository=self.repo,
        )

    async def message(self, text, reply=None):
        self.session.next_message_id += 1
        msg = Message(
            message_id=self.session.next_message_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=self.user,
            text=text,
            reply_to_message=reply,
        )
        await self.feed(message=msg)
        return msg

    def button(self, action):
        for msg in reversed(list(self.session.messages.values())):
            if msg.reply_markup:
                for row in msg.reply_markup.inline_keyboard:
                    for button in row:
                        if (
                            button.callback_data
                            and button.callback_data.partition("~")[0] == action
                        ):
                            return msg, button.callback_data
        raise AssertionError(f"No button {action}")

    async def click(self, action=None, saved=None):
        msg, data = saved or self.button(action)
        await self.feed(
            callback_query=CallbackQuery(
                id=str(uuid4()),
                from_user=self.user,
                chat_instance="synthetic",
                message=msg,
                data=data,
            )
        )

    async def current(self):
        return copy.deepcopy(await self.store.state(42))


async def start_story(repo, monkeypatch, ordinary=13, position=1, display="auto"):
    original_random = mixed_training.secrets.SystemRandom

    class OrderedRandom(original_random):
        def shuffle(self, seq):
            if seq and all(isinstance(n, int) for n in seq):
                # A deterministic observation of the actual shuffled Mix, not a fixed-mode entry.
                seq.sort(key=lambda n: (n != 1, n != ordinary, n))
            else:
                super().shuffle(seq)

    scenario = mixed_training._scenario(seed=192508)
    monkeypatch.setattr(mixed_training.secrets, "SystemRandom", OrderedRandom)
    monkeypatch.setattr(mixed_training, "_scenario", lambda **kwargs: scenario)
    flow = Flow(repo)
    await repo.register_user(42)
    await repo.set_math_display(42, display)
    await flow.message("/start")
    await flow.click("nav:mixed")
    state = await flow.current()
    assert state["state"]["available_numbers"] == mixed_training.available_numbers()
    assert state["state"]["queue"][0] == ordinary
    for _ in range(position - 1):
        problem = (await flow.current())["problem"]
        await flow.message(str(problem["correct_answer"]))
        await flow.click(f"mixed:next:{problem['problem_id']}")
    assert (await flow.current())["problem"]["number"] == position
    return flow


async def exercise_jump(repo, monkeypatch, ordinary, position, display="auto"):
    h = await start_story(repo, monkeypatch, ordinary, position, display)
    try:
        before = await h.current()
        problem = before["problem"]
        saved = h.button(f"mixed:skip_story:{problem['problem_id']}")
        old_skip = h.button(f"mixed:skip:{problem['problem_id']}")
        first_call = len(h.session.calls)
        await h.click(saved=saved)
        after = await h.current()
        assert after["id"] == before["id"]
        assert after["status"] == "active"
        assert after["problem"]["number"] == ordinary
        assert after["state"]["scenario_snapshot"] is None
        assert after["state"]["queue"] == before["state"]["queue"][1:]
        assert after["state"]["available_numbers"] == before["state"]["available_numbers"]
        outgoing = h.session.calls[first_call:]
        sends = [
            c
            for c in outgoing
            if c.__api_method__ in {"sendMessage", "sendRichMessage", "sendPhoto"}
        ]
        assert sends and sum(bool(getattr(c, "reply_markup", None)) for c in sends) == 1
        # Only the new ordinary condition, with its normal controls; no skipped story messages.
        assert all("skip_story" not in str(getattr(c, "reply_markup", "")) for c in sends)
        for n in range(position + 1, 6):
            assert not any(f"Задание №{n}" in str(c) for c in sends)
        metrics = (await training_insights(repo, 42))["total"]
        assert metrics["issued"] == position + 1
        assert metrics["correct"] == position - 1
        assert metrics["attempts"] == position - 1
        assert metrics["skipped"] == 1
        assert metrics["failed"] == 0
        exact = after["problem"]["problem_id"]
        await h.click(saved=saved)
        await h.click(saved=old_skip)
        assert (await h.current())["problem"]["problem_id"] == exact
        await h.click(f"mixed:menu:{exact}")
        if isinstance(repo, PostgresRepository):
            h.repo = PostgresRepository(repo._pool)
        h.store = MixedTrainingRepository(h.repo)
        await h.click("nav:resume")
        restored = await h.current()
        assert restored["id"] == before["id"]
        assert restored["problem"]["problem_id"] == exact
        assert restored["problem"]["attempts"] == 0
        assert (await training_insights(repo, 42))["total"] == metrics
    finally:
        await h.bot.session.close()


@pytest.mark.parametrize("ordinary", [13, 17])
@pytest.mark.parametrize("position", [1, 3, 5])
async def test_random_mix_jump_memory(monkeypatch, ordinary, position):
    await exercise_jump(MemoryRepository(), monkeypatch, ordinary, position)


@pytest.mark.parametrize("ordinary,position", [(13, 1), (17, 3), (13, 5)])
async def test_random_mix_jump_postgres(bank_pool, monkeypatch, ordinary, position):
    await exercise_jump(PostgresRepository(bank_pool), monkeypatch, ordinary, position)


@pytest.mark.parametrize("display", ["auto", "png"])
async def test_standard_next_six_keeps_normal_math_delivery(monkeypatch, display):
    await exercise_jump(MemoryRepository(), monkeypatch, 6, 1, display)


async def test_single_skip_and_old_message_guard(monkeypatch):
    h = await start_story(MemoryRepository(), monkeypatch)
    try:
        initial = (await h.current())["problem"]
        await h.click(f"mixed:skip:{initial['problem_id']}")
        second = (await h.current())["problem"]
        assert second["number"] == 2
        stale = h.button(f"mixed:skip_story:{second['problem_id']}")
        await h.click(f"mixed:menu:{second['problem_id']}")
        await h.click("nav:resume")
        await h.click(saved=stale)
        assert (await h.current())["problem"]["problem_id"] == second["problem_id"]
        await h.click(f"mixed:skip_story:{second['problem_id']}")
        assert (await h.current())["problem"]["number"] == 13
    finally:
        await h.bot.session.close()


@pytest.mark.parametrize("competitor", ["skip_story", "skip", "answer", "plain_answer"])
async def test_postgres_story_skip_races(bank_pool, monkeypatch, competitor):
    h = await start_story(PostgresRepository(bank_pool), monkeypatch, ordinary=6, position=3)
    try:
        before = await h.current()
        p = before["problem"]
        story = h.button(f"mixed:skip_story:{p['problem_id']}")
        other = (
            h.message(str(p["correct_answer"]), reply=story[0] if competitor == "answer" else None)
            if competitor in {"answer", "plain_answer"}
            else h.click(f"mixed:{competitor}:{p['problem_id']}")
        )
        await asyncio.gather(h.click(saved=story), other)
        current = (await h.current())["problem"]
        assert current["number"] in ({3, 6} if competitor in {"answer", "plain_answer"} else {4, 6})
        if current["number"] == 3:
            assert current["outcome"] == "solved"
        rows = await bank_pool.fetch("SELECT number,outcome,attempts FROM mixed_training_problems")
        assert len(rows) in {3, 4}
        assert sum(r["number"] == 6 for r in rows) <= 1
        assert sum(r["outcome"] == "skipped" for r in rows) <= 1
        assert not any(r["number"] > 6 for r in rows)
        exact = current["problem_id"]
        await h.click(saved=story)
        assert (await h.current())["problem"]["problem_id"] == exact
    finally:
        await h.bot.session.close()


async def test_failed_candidate_does_not_skip_or_change_queue(monkeypatch):
    h = await start_story(MemoryRepository(), monkeypatch, ordinary=17)
    try:
        before = await h.current()
        action = f"mixed:skip_story:{before['problem']['problem_id']}"
        candidate = mixed_training._candidate

        def unavailable(*args):
            raise RuntimeError("synthetic generator failure")

        monkeypatch.setattr(mixed_training, "_candidate", unavailable)
        await h.click(action)
        assert await h.current() == before
        monkeypatch.setattr(mixed_training, "_candidate", candidate)
        await h.click(action)
        assert (await h.current())["problem"]["number"] == 17
    finally:
        await h.bot.session.close()


async def test_terminal_source_and_pause_do_not_accept_old_story_skip(monkeypatch):
    h = await start_story(MemoryRepository(), monkeypatch, position=3)
    try:
        problem = (await h.current())["problem"]
        old = h.button(f"mixed:skip_story:{problem['problem_id']}")
        await h.click(f"mixed:menu:{problem['problem_id']}")
        paused = await h.current()
        await h.click(saved=old)
        assert await h.current() == paused
        await h.click("nav:resume")
        await h.message(str(problem["correct_answer"]))
        completed = await h.current()
        await h.click(saved=old)
        assert await h.current() == completed
        assert completed["problem"]["outcome"] == "solved"
        buttons = mixed_training._mixed_menu(problem["problem_id"], completed=True, scenario=True)
        assert "skip_story" not in str(buttons)
        assert "skip_story" not in str(mixed_training._mixed_menu("ordinary", scenario=False))
    finally:
        await h.bot.session.close()


async def test_cycle_boundary_keeps_future_story_slot_and_settings(monkeypatch):
    h = await start_story(MemoryRepository(), monkeypatch, ordinary=13)
    try:
        raw = h.repo._mixed_training_sessions[42]
        raw["state"]["queue"] = []
        raw["state"]["available_numbers"] = [1, 13, 17]
        problem = (await h.current())["problem"]
        await h.click(f"mixed:skip_story:{problem['problem_id']}")
        state = await h.current()
        assert state["problem"]["number"] == 13
        assert state["state"]["queue"] == [1, 17]
        assert state["state"]["available_numbers"] == [1, 13, 17]
    finally:
        await h.bot.session.close()


async def test_story_only_combination_is_not_finished_or_replaced(monkeypatch):
    h = await start_story(MemoryRepository(), monkeypatch)
    try:
        raw = h.repo._mixed_training_sessions[42]
        raw["state"].update(queue=[], available_numbers=[1])
        before = await h.current()
        await h.click(f"mixed:skip_story:{before['problem']['problem_id']}")
        assert await h.current() == before
    finally:
        await h.bot.session.close()


async def test_postgres_new_issue_failure_rolls_back_skip(bank_pool, monkeypatch):
    import asyncpg

    h = await start_story(PostgresRepository(bank_pool), monkeypatch)
    try:
        before = await h.current()
        p = before["problem"]
        duplicate_id = {**mixed_training._candidate(13), "problem_id": p["problem_id"]}
        with pytest.raises(asyncpg.UniqueViolationError):
            await h.store.skip_story(
                42,
                p["problem_id"],
                before["revision"],
                p["prompt_message_id"],
                before["state"]["queue"],
                duplicate_id,
            )
        assert await h.current() == before
        assert await bank_pool.fetchval("SELECT count(*) FROM mixed_training_problems") == 1
    finally:
        await h.bot.session.close()


async def test_delivery_failure_resumes_the_committed_ordinary_snapshot(monkeypatch):
    from aiogram.exceptions import TelegramNetworkError

    from app.bot.presentation import MathDeliveryUncertain

    h = await start_story(MemoryRepository(), monkeypatch, ordinary=17)
    try:
        p = (await h.current())["problem"]
        old = h.button(f"mixed:skip_story:{p['problem_id']}")
        original_send = h.session.make_request

        async def fail_photo(bot, method, timeout=None):  # noqa: ASYNC109
            if method.__api_method__ in {"sendPhoto", "sendRichMessage"}:
                raise TelegramNetworkError(method=method, message="synthetic uncertain send")
            return await original_send(bot, method, timeout)

        monkeypatch.setattr(h.session, "make_request", fail_photo)
        with pytest.raises(MathDeliveryUncertain):
            await h.click(saved=old)
        committed = (await h.current())["problem"]
        assert committed["number"] == 17
        monkeypatch.setattr(h.session, "make_request", original_send)
        await h.click(saved=old)
        assert (await h.current())["problem"]["problem_id"] == committed["problem_id"]
        await h.message("/start")
        await h.click("nav:resume")
        assert (await h.current())["problem"]["problem_id"] == committed["problem_id"]
        assert (await training_insights(h.repo, 42))["total"]["skipped"] == 1
    finally:
        await h.bot.session.close()
