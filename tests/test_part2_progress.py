from decimal import Decimal

from app.bot.progress_image import dashboard_tile_values
from app.config import Settings
from app.part2_grading import Assessment
from app.persistence.part2_grades import finish, reserve
from app.persistence.part2_insights import history, revision, summary
from app.persistence.part2_training import Part2Training


async def test_first_scores_revisions_hints_and_private_history(bank_pool):
    bank = Part2Training(bank_pool)
    issue = await bank.open(1, 25)
    s = Settings(oge_grading_daily_user_limit=10, oge_grading_monthly_budget_usd=100)
    for attempt, (status, score) in enumerate(
        [("graded", 1), ("uncertain", None), ("graded", 2)], 1
    ):
        assert await bank.append(1, issue, attempt, attempt, f"Решение {attempt}", None, 4)
        assert (await reserve(bank_pool, s, 1, issue, attempt))[1]
        report = Assessment(
            status=status,
            score=score,
            max_score=2,
            correct_steps=[],
            errors=[],
            feedback="По критерию.",
            next_step="",
            needs_review=score is None,
            confidence=0.7,
        )
        await finish(bank_pool, s, issue, attempt, (report, 20, 10, "offline"), dispatched=True)
    await bank_pool.execute("UPDATE part2_issues SET hints=2 WHERE id=$1", issue)
    data = await summary(bank_pool, 1)
    assert {
        k: data[25][k]
        for k in [
            "issued",
            "checked",
            "first_full",
            "first_graded",
            "first_points",
            "points",
            "revisions",
            "unclear",
            "ones",
            "twos",
            "hints",
        ]
    } == {
        "issued": 1,
        "checked": 2,
        "first_full": 0,
        "first_graded": 1,
        "first_points": 1,
        "points": 3,
        "revisions": 2,
        "unclear": 1,
        "ones": 1,
        "twos": 1,
        "hints": 2,
    }
    assert dashboard_tile_values({"written": data}, 25)[-1] == (25, 0, 1, "0%", False)
    assert (await history(bank_pool, 1, 0))[0]["id"] == issue
    assert await history(bank_pool, 2, 0) == []
    assert await revision(bank_pool, 2, issue, 1) is None
    for attempt in (1, 2, 3):
        _, work = await revision(bank_pool, 1, issue, attempt)
        assert [r["body"] for r in work] == [f"Решение {attempt}"]
    await bank_pool.execute("UPDATE part2_work SET created_at=now()-interval '8 days'")
    _, old_work = await revision(bank_pool, 1, issue, 1)
    assert old_work[0]["body"] == "Решение 1"
    assert await summary(bank_pool, 1) == data


async def test_written_work_through_number_menu_and_private_history(bank_pool, monkeypatch):
    from datetime import UTC, datetime

    from aiogram import Bot, Dispatcher
    from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User
    from test_inline_dispatcher_postgres import TelegramSession

    from app.bot.router import build_router
    from app.config import get_settings
    from app.persistence.repository import PostgresRepository

    monkeypatch.setattr(get_settings(), "oge_part2_enabled", True)
    repo = PostgresRepository(bank_pool)
    from io import BytesIO

    import httpx
    from aiogram.types import File, PhotoSize
    from openai import AsyncOpenAI
    from PIL import Image
    from pydantic import SecretStr

    from app.bot import part2_check

    buf = BytesIO()
    Image.new("RGB", (100, 80), "white").save(buf, format="JPEG")
    page_bytes = buf.getvalue()

    class AlbumSession(TelegramSession):
        async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
            if method.__api_method__ == "getFile":
                return File(
                    file_id=method.file_id,
                    file_unique_id="demo",
                    file_size=len(page_bytes),
                    file_path="photos/pilot.jpg",
                )
            return await super().make_request(bot, method, timeout)

        async def stream_content(self, *args, **kwargs):
            yield page_bytes

    telegram = AlbumSession()
    bot = Bot("123456:TEST", session=telegram)
    dp = Dispatcher()
    dp.include_router(build_router())
    user = User(id=42, is_bot=False, first_name="Тест")
    chat = Chat(id=42, type="private")
    seq = 1000

    async def post(**fields):
        nonlocal seq
        seq += 1
        await dp.feed_update(bot, Update(update_id=seq, **fields), repository=repo)

    async def text(body, **extra):
        await post(
            message=Message(
                message_id=seq,
                date=datetime.now(UTC),
                chat=chat,
                from_user=user,
                text=body,
                **extra,
            )
        )

    async def tap(action):
        msg = next(
            m
            for m in reversed(telegram.messages.values())
            if m.reply_markup
            and any(
                b.callback_data.partition("~")[0] == action
                for row in m.reply_markup.inline_keyboard
                for b in row
            )
        )
        cb = next(
            b.callback_data
            for row in msg.reply_markup.inline_keyboard
            for b in row
            if b.callback_data.partition("~")[0] == action
        )
        await post(
            callback_query=CallbackQuery(
                id=str(seq), from_user=user, chat_instance="42", message=msg, data=cb
            )
        )

    try:
        await text("/start", entities=[MessageEntity(type="bot_command", offset=0, length=6)])
        await tap("nav:numbers")
        await tap("p2:menu:23")
        assert await repo.user_state(42) == "part2_menu"
        await tap("p2:open:23")
        assert await repo.user_state(42) == "part2"
        current = await Part2Training(bank_pool).current(42)
        issue = current["id"]
        assert any(call.__api_method__ == "sendPhoto" for call in telegram.calls)
        await text("Моё решение.")
        assert (
            await bank_pool.fetchval("SELECT count(*) FROM part2_work WHERE issue_id=$1", issue)
            == 1
        )
        await tap(f"p2:hint:{issue}")
        await tap(f"p2:check:{issue}")
        assert not await bank_pool.fetchval("SELECT count(*) FROM part2_grades")
        # Reuse the same buttons and the persisted draft when grading becomes available.
        import json

        settings = get_settings()
        for key, value in {
            "oge_grading_enabled": True,
            "openai_api_key": SecretStr("mock"),
            "oge_grading_tariff_model": settings.oge_grading_model,
            "oge_grading_input_usd_per_million": Decimal(1),
            "oge_grading_output_usd_per_million": Decimal(2),
            "oge_grading_context_tokens": 16000,
            "oge_grading_monthly_budget_usd": Decimal(1),
        }.items():
            monkeypatch.setattr(settings, key, value)
        requests = []

        def respond(req):
            payload = json.loads(req.content)
            requests.append(payload)
            if len(requests) == 3:
                return httpx.Response(429, json={"error": {"message": "synthetic quota"}})
            score = len(requests)
            assessment = dict(
                status="graded",
                score=score,
                max_score=2,
                needs_review=False,
                confidence=0.8,
                feedback="Баллы по критерию.",
                next_step="Обоснуйте вывод.",
                errors=[],
                correct_steps=[],
            )
            return httpx.Response(
                200,
                json={
                    "id": "resp_x",
                    "object": "response",
                    "status": "completed",
                    "model": settings.oge_grading_model,
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_x",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(assessment),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 400, "output_tokens": 120, "total_tokens": 520},
                },
            )

        def client(**kwargs):
            return AsyncOpenAI(
                **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
            )

        monkeypatch.setattr(part2_check, "AsyncOpenAI", client)
        for page_id in ("a", "b"):
            await post(
                message=Message(
                    message_id=seq,
                    date=datetime.now(UTC),
                    chat=chat,
                    from_user=user,
                    media_group_id="demo-album",
                    photo=[
                        PhotoSize(
                            file_id=page_id,
                            file_unique_id=page_id,
                            width=100,
                            height=80,
                            file_size=len(page_bytes),
                        )
                    ],
                )
            )
        assert requests == []
        await tap(f"p2:check:{issue}")
        assert len(requests) == 1
        assert (
            len([v for v in requests[0]["input"][1]["content"] if v["type"] == "input_image"]) == 2
        )
        await tap(f"p2:check:{issue}")
        assert len(requests) == 1
        await text("Исправленная работа.")
        await tap(f"p2:check:{issue}")
        await text("Ещё один вариант.")
        await tap(f"p2:check:{issue}")
        assert len(requests) == 3
        scores = await bank_pool.fetch("SELECT status,score FROM part2_grades ORDER BY revision")
        assert [tuple(r.values()) for r in scores] == [
            ("graded", 1),
            ("graded", 2),
            ("error", None),
        ]
        await tap("nav:main")
        await tap("nav:resume")
        assert (await Part2Training(bank_pool).current(42))["id"] == issue
        await tap("nav:main")
        await tap("nav:progress")
        await tap("progress:works:0")
        await tap(f"progress:work:{issue}:1:0")
        assert any("Моё решение." in (getattr(c, "text", None) or "") for c in telegram.calls)
    finally:
        await bot.session.close()
