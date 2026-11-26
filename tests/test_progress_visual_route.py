"""Real progress callbacks and PostgreSQL reads with a synthetic Telegram transport."""

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User
from PIL import Image
from test_inline_dispatcher_postgres import TelegramSession
from test_navigation_postgres import navigation_pool as navigation_pool

from app.adaptive.skills import title
from app.bot import visual_delivery
from app.bot.adaptive import catalog
from app.bot.router import build_router
from app.config import Settings, test_settings
from app.math.generator import generate as generate_task6
from app.math.inequalities import generate as generate_task13
from app.persistence.repository import PostgresRepository
from app.persistence.training_insights import training_insights

__all__ = ["navigation_pool"]


def progress_settings(**changes):
    return Settings(_env_file=None, **{
        "oge_adaptive_enabled": True,
        "oge_part2_enabled": False,
        "oge_visual_progress_journal_enabled": True,
        "oge_visual_number_progress_enabled": True,
        "oge_visual_user_ids": "42",
        **changes,
    })


async def seed_progress(repository):
    """Use valid generator snapshots and record an explicit synthetic outcome mix."""
    await repository.register_user(42)
    groups = {
        number: sorted(
            (family for family, position in catalog().items() if position == number),
            key=lambda family: (-len(title(family)), family),
        )[:6] for number in (6, 13)
    }
    assert all(len(families) == 6 for families in groups.values())
    cases = [
        (13, index, status)
        for index, status in enumerate(("retry", "first", "hinted", "legacy", "failed", "review"))
    ] + [
        (6, index, status)
        for index, status in enumerate(
            ("retry",) * 7 + ("skip", "review", "hinted", "legacy", "retry")
        )
    ]
    outcomes = {"skip": "skipped", "review": "solution_viewed", "failed": "failed"}
    answers = {
        "retry": (False, True), "first": (True,), "hinted": (True,), "failed": (False, False),
    }
    created = datetime(2026, 11, 26, 10, tzinfo=UTC)
    async with repository._pool.acquire() as connection, connection.transaction():
        owner = await connection.fetchval("SELECT id FROM users WHERE telegram_user_id=42")
        for slot, (number, index, status) in enumerate(cases):
            family = groups[number][index % 6]
            generator = generate_task6 if number == 6 else generate_task13
            problem = generator(family, 7001 + slot)
            snapshot = problem.to_snapshot()
            problem_id = UUID(problem.problem_id)
            timestamp = created + timedelta(minutes=slot)
            has_hint = status in {"hinted", "review"}
            review = timestamp if status in {"review", "failed"} else None
            await connection.execute(
                """INSERT INTO issued_problems
                   (id,user_id,family_id,generator_version,seed,fingerprint,snapshot,outcome,
                    issued_at,hints_used,solution_viewed_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11)""",
                problem_id, owner, family, problem.generator_version, problem.seed,
                problem.fingerprint, json.dumps(snapshot), outcomes.get(status, "solved"),
                timestamp, int(has_hint), review,
            )
            for attempt, correct in enumerate(answers.get(status, ()), 1):
                answer = str(snapshot["correct_answer"])
                await connection.execute(
                    """INSERT INTO attempts
                       (problem_id,user_id,attempt_no,raw_answer,is_correct,used_hint,created_at)
                       VALUES($1,$2,$3,$4,$5,$6,$7)""",
                    problem_id, owner, attempt,
                    answer if correct else ("1" if answer != "1" else "2"),
                    correct, has_hint, timestamp + timedelta(seconds=attempt),
                )


def actions(message, prefix=""):
    if message.reply_markup is None:
        return []
    return [
        button.callback_data.partition("~")[0]
        for row in message.reply_markup.inline_keyboard for button in row
        if button.callback_data and button.callback_data.startswith(prefix)
    ]


def photo_filename(method):
    if method.__api_method__ == "editMessageMedia":
        return getattr(method.media.media, "filename", "")
    if method.__api_method__ == "sendPhoto":
        return getattr(method.photo, "filename", "")
    return ""


class ProgressRoute:
    def __init__(self, repository, settings=None):
        self.repository = repository
        self.settings = settings or progress_settings()
        self.transport = ProgressTelegramSession()
        self.bot = Bot("123456:TEST", session=self.transport)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(build_router())
        self.user = User(id=42, is_bot=False, first_name="Синтетический ученик")
        self.chat = Chat(id=42, type="private")
        self.update_id = 0

    @property
    def current(self):
        return next(message for message in reversed(self.transport.messages.values())
                    if message.reply_markup)

    async def feed(self, **kwargs):
        self.update_id += 1
        token = test_settings.set(self.settings)
        try:
            await self.dispatcher.feed_update(
                self.bot, Update(update_id=self.update_id, **kwargs), repository=self.repository,
            )
        finally:
            test_settings.reset(token)

    async def start(self):
        await self.feed(message=Message(
            message_id=1, date=datetime.now(UTC), chat=self.chat, from_user=self.user,
            text="/start",
            entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        ))
        return await self.click("nav:progress")

    async def click(self, action, *, source=None):
        source = source or self.current
        code = next(
            button.callback_data
            for row in source.reply_markup.inline_keyboard for button in row
            if button.callback_data and button.callback_data.partition("~")[0] == action
        )
        await self.feed(callback_query=CallbackQuery(
            id=f"progress-{self.update_id}", from_user=self.user, chat_instance="progress-test",
            message=source, data=code,
        ))
        return self.current


class ProgressTelegramSession(TelegramSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        if method.__api_method__ == "editMessageText":
            message = self.messages.get(method.message_id)
            if message is not None and message.photo:
                self.calls.append(method)
                raise TelegramBadRequest(method=method, message="there is no text to edit")
        return await super().make_request(bot, method, timeout=timeout)


async def test_visual_progress_dispatcher_keeps_filter_page_and_message_identity(
    navigation_pool, monkeypatch,
):
    repository = PostgresRepository(navigation_pool)
    await seed_progress(repository)
    route = ProgressRoute(repository)
    cards = []
    render = visual_delivery._render_png

    def capture(card):
        cards.append(card)
        png = render(card)
        if card.screen in {"progress_numbers", "number_progress", "progress_journal"}:
            with Image.open(BytesIO(png)) as image:
                assert image.height * 430 <= image.width * 440
        return png

    monkeypatch.setattr(visual_delivery, "_render_png", capture)
    visual_delivery._render_menu_png.cache_clear()
    try:
        overview = await route.start()
        assert overview.photo and "progress:details" in actions(overview)
        number_picker = await route.click("progress:details")
        assert cards[-1].screen == "progress_numbers" and number_picker.photo
        assert actions(number_picker, "progress:number:") == [
            f"progress:number:{number}" for number in range(1, 20)
        ]
        assert number_picker.reply_to_message.message_id == overview.message_id
        before = len(route.transport.calls)
        detail = await route.click("progress:number:6")
        assert detail.photo and cards[-1].screen == "number_progress"
        assert detail.message_id == number_picker.message_id
        assert detail.reply_to_message.message_id == overview.message_id
        (edit,) = [method for method in route.transport.calls[before:]
                   if photo_filename(method) == "bop-number-progress.png"]
        assert edit.__api_method__ == "editMessageMedia" and edit.reply_markup
        assert detail.reply_markup != number_picker.reply_markup
        before = len(route.transport.calls)
        await route.click("progress:number:9", source=number_picker)
        assert route.current.reply_markup == detail.reply_markup
        assert all(method.__api_method__ == "answerCallbackQuery"
                   for method in route.transport.calls[before:])
        types = await route.click("progress:family:6:0")
        assert types.photo and types.message_id == detail.message_id
        await route.click("progress:number:6")
        journal = await route.click("progress:numhist:6:0")
        assert journal.photo and journal.message_id == detail.message_id
        assert len(actions(journal, "progress:item:")) == 4
        assert cards[-1].screen == "progress_journal"
        entries = cards[-1].sections[0].entries
        assert entries[0].value == "Верно со 2-й попытки" and entries[0].icon == "had_error"
        assert entries[1].value == "Верно" and not entries[1].icon
        assert entries[2].value == "Верно с подсказкой" and not entries[2].icon
        assert "progress:numerr:6:0" in actions(journal)
        assert "progress:numhist:6:4" in actions(journal)

        await route.click("progress:numerr:6:0")
        errors = await route.click("progress:numerr:6:4")
        previous = actions(errors, "progress:item:")
        assert len(previous) == 4 and all(action.endswith(":n6.4") for action in previous)
        assert "progress:numerr:6:0" in actions(errors)
        await route.click(previous[0])
        record = route.current
        assert "Исходное условие:" in (record.text or record.caption or "")
        assert "Ошибка была: да" in (record.text or record.caption or "")
        await route.click(previous[0].replace(":item:", ":solution:"))
        await route.click("progress:numerr:6:4")
        assert actions(route.current, "progress:item:") == previous
        await route.click(previous[0])
        await route.click("progress:return:n6.4")
        assert actions(route.current, "progress:item:") == previous

        await route.click("progress:filter:n6.4")
        await route.click("progress:errors:0")
        await route.click("progress:filter:e0")
        await route.click("progress:numerr:13:0")
        assert route.current.photo and "progress:numhist:13:0" in actions(route.current)
        assert len(actions(route.current, "progress:item:")) == 2
        await route.click("progress:summary")
        assert route.current.message_id == overview.message_id

        await route.click("progress:history:0")
        journal = route.current
        assert journal.reply_to_message.message_id == overview.message_id
        before = len(route.transport.calls)
        await route.click("progress:errors:0")
        assert route.current.message_id == journal.message_id
        edits = [m for m in route.transport.calls[before:]
                 if photo_filename(m) == "bop-progress-journal.png"]
        assert len(edits) == 1 and edits[0].__api_method__ == "editMessageMedia"
        assert edits[0].message_id == journal.message_id and edits[0].reply_markup
        attempts = await training_insights(repository, 42)
        assert attempts["numbers"][6]["second_correct"] == 8
    finally:
        visual_delivery._render_menu_png.cache_clear()
        await route.bot.session.close()


async def test_visual_journal_render_failure_keeps_same_filter_and_page_size(
    navigation_pool, monkeypatch,
):
    repository = PostgresRepository(navigation_pool)
    await seed_progress(repository)
    route = ProgressRoute(repository)
    render = visual_delivery._render_png

    def fail_for_journal(card):
        if card.screen == "progress_journal":
            raise ValueError("synthetic render failure")
        return render(card)

    monkeypatch.setattr(visual_delivery, "_render_png", fail_for_journal)
    try:
        overview = await route.start()
        journal = await route.click("progress:history:0")
        assert not journal.photo and "История и ошибки" in (journal.text or "")
        assert journal.reply_to_message.message_id == overview.message_id
        assert len(actions(journal, "progress:item:")) == 4
        errors = await route.click("progress:errors:0")
        assert not errors.photo and "С ошибками" in (errors.text or "")
        await route.click("progress:errors:4")
        assert all(a.endswith(":e4") for a in actions(route.current, "progress:item:"))
        assert "progress:errors:0" in actions(route.current)

        await route.click("progress:summary")
        assert route.current.message_id == overview.message_id
        route.settings = progress_settings(oge_visual_user_ids="")
        journal = await route.click("progress:history:0")
        assert not journal.photo and len(actions(journal, "progress:item:")) == 6
        assert "progress:history:6" in actions(journal)
    finally:
        await route.bot.session.close()
