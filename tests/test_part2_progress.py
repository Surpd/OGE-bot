from decimal import Decimal

from app.bot.progress_image import dashboard_tile_values
from app.config import Settings
from app.part2_grading import Assessment, Grade
from app.persistence.part2_grades import finish, reserve
from app.persistence.part2_insights import history, revision, summary
from app.persistence.part2_training import Part2Training


async def test_first_scores_revisions_hints_and_private_history(bank_pool):
    bank = Part2Training(bank_pool)
    issue = await bank.open(1, 25)
    s = Settings(oge_grading_daily_user_limit=10, oge_grading_monthly_budget_usd=5)
    for attempt, (status, score) in enumerate(
        [("graded", 1), ("uncertain", None), ("graded", 2)], 1
    ):
        assert (
            await bank.append(1, issue, attempt, attempt, f"Решение {attempt}", "photo") == "saved"
        )
        assert (await reserve(bank_pool, s, 1, issue, attempt))[1]
        report = Assessment(
            status=status,
            score=score,
            max_score=2,
            criterion_evidence=(
                [{"criterion": "Обоснование", "student_evidence": "Проверка"}]
                if score is not None
                else []
            ),
            correct_steps=[],
            errors=[],
            feedback="По критерию.",
            next_step="",
            needs_review=score is None,
            confidence=0.7,
        )
        await finish(
            bank_pool,
            s,
            issue,
            attempt,
            Grade(report, 20, 10, "offline", Decimal("0.00014")),
            dispatched=True,
        )
        await bank_pool.execute("UPDATE part2_grades SET created_at=now()-interval '21 seconds'")
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
        message_id = await bank_pool.fetchval(
            "SELECT (current_state->>'navigation_message_id')::int "
            "FROM users WHERE telegram_user_id=$1",
            user.id,
        )
        msg = telegram.messages[message_id]
        cb = next(
            b.callback_data
            for row in msg.reply_markup.inline_keyboard
            for b in row
            if (
                b.callback_data.partition("~")[0] == action
                or action.startswith("p2:check:")
                and b.callback_data.startswith(action + ":")
            )
        )
        query = CallbackQuery(id=str(seq), from_user=user, chat_instance="42", message=msg, data=cb)
        await post(callback_query=query)
        return query

    try:
        await text("/start", entities=[MessageEntity(type="bot_command", offset=0, length=6)])
        await tap("nav:numbers")
        await tap("nav:numbers:1")
        await tap("nav:numbers:2")
        await tap("nav:numbers:3")
        await tap("p2:menu:23")
        assert await repo.user_state(42) == "part2_menu"
        # Freeze the random choice to an actual card with a condition figure.
        await bank_pool.execute("""UPDATE part2_versions SET available=false
            WHERE (payload->>'number')='23' AND task_id<>'oge-part2-reshu-315053'""")
        open_query = await tap("p2:open:23")
        # Two separate updates carrying the consumed revision must not issue another card.
        await post(callback_query=open_query)
        assert await bank_pool.fetchval("SELECT count(*) FROM part2_issues WHERE owner=42") == 1
        assert await repo.user_state(42) == "part2"
        current = await Part2Training(bank_pool).current(42)
        issue = current["id"]
        assert any(
            call.__api_method__ == "sendRichMessage" and call.rich_message.media
            for call in telegram.calls
        )
        await text("Моё решение.")
        assert (
            await bank_pool.fetchval("SELECT count(*) FROM part2_work WHERE issue_id=$1", issue)
            == 0
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
            "oge_grading_context_tokens": 16000,
            "oge_grading_monthly_budget_usd": Decimal(1),
        }.items():
            monkeypatch.setattr(settings, key, value)
        requests = []

        def respond(req):
            payload = json.loads(req.content)
            if req.url.path.endswith("/input_tokens"):
                return httpx.Response(
                    200, json={"object": "response.input_tokens", "input_tokens": 400}
                )
            requests.append(payload)
            if len(requests) == 3:
                return httpx.Response(429, json={"error": {"message": "synthetic quota"}})
            score = min(2, len(requests))
            context = json.loads(payload["input"][0]["content"][0]["text"])
            assessment = dict(
                status="graded",
                score=score,
                max_score=2,
                needs_review=False,
                confidence=0.8,
                feedback="Баллы по критерию.",
                next_step="Обоснуйте вывод.",
                errors=[],
                criterion_evidence=[
                    {
                        "criterion": context["rubric"]["levels"][str(score)]["rule"],
                        "student_evidence": "Корень проверен.",
                    }
                ],
                correct_steps=["Корень проверен."],
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
                    "usage": {
                        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                        "input_tokens": 400,
                        "output_tokens": 120,
                        "total_tokens": 520,
                    },
                },
            )

        def client(_settings):
            return AsyncOpenAI(
                api_key="mock",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            )

        monkeypatch.setattr(part2_check, "open_client", client)

        def photo_message(page_id, *, album=None, reply=None, caption=None):
            return Message(
                message_id=seq,
                date=datetime.now(UTC),
                chat=chat,
                from_user=user,
                media_group_id=album,
                reply_to_message=reply or telegram.messages[current["prompt_message_id"]],
                caption=caption,
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

        current = await Part2Training(bank_pool).current(42)
        await post(message=photo_message("album-a", album="demo-album"))
        first_photo = photo_message("a", caption="Старый снимок.")
        await post(message=first_photo)
        await post(message=photo_message("b", album="demo-album"))
        assert any(
            "Альбом не принят" in (getattr(call, "text", None) or "") for call in telegram.calls
        )
        replacement = photo_message("c", reply=first_photo, caption="Моё решение.")
        await post(message=replacement)
        await post(message=replacement)
        saved = await bank_pool.fetch(
            "SELECT photo FROM part2_work WHERE issue_id=$1 AND photo IS NOT NULL", issue
        )
        assert [r["photo"] for r in saved] == ["c"]
        assert requests == []
        await tap(f"p2:check:{issue}")
        assert len(requests) == 1
        assert (
            len([v for v in requests[0]["input"][1]["content"] if v["type"] == "input_image"]) == 1
        )
        assert requests[0]["input"][1]["content"][0]["text"].count("Моё решение.") == 0
        assert "Старый снимок." not in str(requests[0]["input"])
        assert (
            len([v for v in requests[0]["input"][0]["content"] if v["type"] == "input_image"]) == 1
        )
        assert any(
            "Почему именно 1 балл"
            in (
                getattr(call, "text", None)
                or getattr(getattr(call, "rich_message", None), "html", "")
            )
            for call in telegram.calls
        )
        await tap(f"p2:check:{issue}")
        assert len(requests) == 1
        await bank_pool.execute("UPDATE part2_grades SET dispatched_at=now()-interval '21 seconds'")
        await post(message=photo_message("d"))
        await tap(f"p2:check:{issue}")
        await bank_pool.execute("UPDATE part2_grades SET dispatched_at=now()-interval '21 seconds'")
        await post(message=photo_message("e"))
        await tap(f"p2:check:{issue}")
        assert len(requests) == 3
        scores = await bank_pool.fetch("SELECT status,score FROM part2_grades ORDER BY revision")
        assert [tuple(r.values()) for r in scores] == [
            ("graded", 1),
            ("graded", 2),
            ("error", None),
        ]
        await tap("p2:menu:23")
        await tap("nav:numbers")
        await tap("nav:main")
        await tap("nav:resume")
        assert (await Part2Training(bank_pool).current(42))["id"] == issue
        await tap("p2:menu:23")
        await tap("nav:numbers")
        await tap("nav:main")
        await tap("nav:progress")
        await tap("progress:works:0")
        await tap(f"progress:work:{issue}:1:0")
        assert any("Моё решение." in (getattr(c, "text", None) or "") for c in telegram.calls)
        from app.bot import api_diagnostics

        def diagnostic_api(req):
            if req.url.path.endswith("/models/gpt-6.1-terra"):
                return httpx.Response(200, json={"id": "gpt-6.1-terra", "object": "model"})
            return respond(req)

        def diagnostic_client(_settings):
            return AsyncOpenAI(
                api_key="mock",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(diagnostic_api)),
            )

        monkeypatch.setattr(api_diagnostics, "open_client", diagnostic_client)
        await text("/api_status")
        status = next(
            call.text
            for call in reversed(telegram.calls)
            if "Баланс API-кредитов" in (getattr(call, "text", None) or "")
        )
        assert "gpt-6.1-terra · reasoning low · доступна" in status
        assert "Сегодня: 3/25 · Месяц: 3/150" in status
        assert "Учтено: $0.002000 · в резерве: $0.060480" in status
        assert "Средняя стоимость учтённых проверок: $0.0010000" in status
        assert status.count("400 / 120 токенов") == 2
        await bank_pool.execute("UPDATE part2_grades SET dispatched_at=now()-interval '21 seconds'")
        confirm = seq
        await text("/api_test")
        assert len(requests) == 3
        previous = await tap(f"p2:apitest:{confirm}")
        await post(callback_query=previous)
        assert len(requests) == 4
        diag = await bank_pool.fetchrow("SELECT * FROM part2_api_tests")
        assert (diag["score"], diag["input_tokens"], diag["output_tokens"]) == (2, 400, 120)
        assert diag["cost_usd"] == Decimal("0.001")
        assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 3

        # A paged type menu issues one card even when Telegram redelivers the callback.
        await tap("nav:numbers")
        await tap("nav:numbers:1")
        await tap("nav:numbers:2")
        await tap("p2:menu:22")
        await tap("p2:menu:22:1")
        await tap("p2:menu:22:0")
        replay = await tap("p2:open:22")
        await post(callback_query=replay)
        bank = Part2Training(bank_pool)
        other = await bank.current(42)
        assert other["number"] == 22
        assert await bank_pool.fetchval("SELECT count(*) FROM part2_issues WHERE number=22") == 1
        current = other
        await post(message=photo_message("graph", caption="Черновик графика."))
        # The photo confirmation intentionally has only Check/Remove. /start preserves the draft.
        await text("/start", entities=[MessageEntity(type="bot_command", offset=0, length=6)])
        await tap("nav:numbers")
        await tap("nav:numbers:1")
        await tap("nav:numbers:2")
        await tap("nav:numbers:3")
        await tap("p2:menu:23")
        dp = Dispatcher()
        dp.include_router(build_router())
        repo = PostgresRepository(bank_pool)
        await tap(f"p2:resume:{issue}")
        assert (await bank.current(42))["id"] == issue
        await tap("p2:menu:23")
        await tap("nav:numbers")
        await tap("nav:numbers:1")
        await tap("nav:numbers:2")
        await tap("p2:menu:22")
        await tap(f"p2:resume:{other['id']}")
        assert (await bank.current(42))["draft"]
        await tap(f"p2:draft:{other['id']}")
        assert any("Черновик графика." in (m.text or "") for m in telegram.messages.values())
        await tap(f"p2:resume:{other['id']}")
        await tap(f"p2:solution:{other['id']}")
        assert (await bank.current(42))["solution_viewed_at"] is None
        await tap(f"p2:reveal:{other['id']}")
        assert (await bank.current(42))["solution_viewed_at"] is not None
        await tap(f"p2:finish:{other['id']}")
        assert await bank.current(42, other["id"]) is None
        assert len(requests) == 4
        assert all(
            len(button.callback_data.encode()) <= 64
            for m in telegram.messages.values()
            if m.reply_markup
            for row in m.reply_markup.inline_keyboard
            for button in row
        )

    finally:
        await bot.session.close()
