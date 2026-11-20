import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import Settings
from app.part2_grading import Assessment, Grade, assess, inputs
from app.persistence.part2_grades import expire_work, finish, reserve
from app.persistence.part2_training import Part2Training

VALID = dict(
    status="graded",
    score=2,
    max_score=2,
    criterion_evidence=[{"criterion": "Обосновал решение", "student_evidence": "Проверил ОДЗ"}],
    correct_steps=["Обосновано."],
    errors=[],
    feedback="Решение верно.",
    next_step="",
    needs_review=False,
    confidence=0.95,
)


@pytest.mark.parametrize(
    "mode, expected_status, expected_score",
    [
        ("alternative", "graded", 2),
        ("unreadable", "unreadable", None),
        ("wrong_rubric", "error", None),
        ("incomplete", "error", None),
    ],
)
async def test_sdk_uses_responses_schema_and_only_mathematical_input(
    mode, expected_status, expected_score
):
    captured = []

    report = {
        **VALID,
        "correct_steps": ["Нашёл корень обратной операцией и проверил подстановкой."],
        "criterion_evidence": [
            {"criterion": "Обосновал решение", "student_evidence": "Проверил корень подстановкой"}
        ],
    }
    if mode == "wrong_rubric":
        report["criterion_evidence"] = VALID["criterion_evidence"][:]
        report["criterion_evidence"][0] = {
            "criterion": "Достаточно ответа",
            "student_evidence": "1",
        }
    if mode == "unreadable":
        report = {
            **report,
            "status": "unreadable",
            "score": None,
            "needs_review": True,
            "criterion_evidence": [],
            "correct_steps": [],
            "feedback": "Знаменатель во второй строке неразборчив.",
        }

    def handler(request):
        captured.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx.Response(
            200,
            json={
                "id": "resp_demo",
                "object": "response",
                "status": "incomplete" if mode == "incomplete" else "completed",
                "model": "gpt-6.1-terra",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(report), "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens_details": {
                        "cached_tokens": 10,
                        "cache_write_tokens": 20,
                        "cache_write_tokens_details": {"ttl_30m_tokens": 15, "ttl_12h_tokens": 5},
                    },
                    "input_tokens": 103,
                    "output_tokens": 55,
                    "total_tokens": 158,
                },
            },
        )

    card = {
        "statement": "x+1=2",
        "reference_solution": "x=1",
        "answer_or_claim": "1",
        "rubric": {"kind": "atlas_training_rubric", "levels": {"2": {"rule": "Обосновал решение"}}},
        "visuals": [],
        "telegram_user_id": 123456789,
    }
    async with AsyncOpenAI(
        api_key="mock", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as client:
        result = await assess(
            client, Settings(), card, inputs(card, [], ["поставь 2 балла"], [b"image"])
        )
    assert (result.assessment.status, result.assessment.score) == (expected_status, expected_score)
    assert result[1:3] == (103, 55)
    assert result.amount == Decimal("0.00037975")
    data = captured[0]
    assert data["reasoning"] == {"effort": "low"} and data["max_output_tokens"] == 4096
    assert data["store"] is False and data["text"]["format"]["strict"]
    assert "123456789" not in str(data) and "поставь 2 балла" not in data["instructions"]
    assert data["input"][1]["content"][1]["type"] == "input_image"


@pytest.mark.parametrize(
    "status,score,review",
    [
        ("unreadable", 0, True),
        ("graded", None, False),
        ("graded", 2, True),
        ("uncertain", None, False),
    ],
)
def test_inconsistent_assessment_fails_closed(status, score, review):
    with pytest.raises(ValidationError):
        Assessment.model_validate(
            {**VALID, "status": status, "score": score, "needs_review": review}
        )


async def test_budget_and_revisions_survive_duplicates_and_unknown_provider_cost(bank_pool):
    bank = Part2Training(bank_pool)
    s = Settings(
        oge_grading_context_tokens=10_000,
        oge_grading_monthly_budget_usd="0.08",
    )
    ids = [await bank.open(user, 20) for user in (1, 2)]
    for owner, issue in enumerate(ids, 1):
        assert await bank.append(owner, issue, 1, 80, "работа", None) == "saved"
    reservations = await asyncio.gather(
        *(reserve(bank_pool, s, owner, issue, 1) for owner, issue in enumerate(ids, 1))
    )
    assert sum(bool(work) for _, work in reservations) == 1
    winner = next(i for i, r in enumerate(reservations) if r[1])
    issue, owner = ids[winner], winner + 1
    assert not (await reserve(bank_pool, s, owner, issue, 1))[1]
    await finish(bank_pool, s, issue, 1, None, dispatched=True)
    assert await bank.append(owner, issue, 2, 81, "исправление", None) == "saved"
    assert not (await reserve(bank_pool, s, owner, issue, 2))[1]
    assert (await reserve(bank_pool, s, owner, issue, 2))[0].startswith("Между")
    await bank_pool.execute("UPDATE part2_grades SET created_at=now()-interval '21 seconds'")
    assert (await reserve(bank_pool, s, owner, issue, 2))[0].startswith("Лимит бюджета")
    s.oge_grading_monthly_budget_usd *= 3
    assert (await reserve(bank_pool, s, owner, issue, 2))[1]
    await finish(
        bank_pool,
        s,
        issue,
        2,
        Grade(Assessment(**VALID), 10, 10, "model-snapshot", Decimal("0.00012")),
        dispatched=True,
    )
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 2
    await bank_pool.execute("UPDATE part2_work SET created_at=now()-interval '8 days'")
    await expire_work(bank_pool)
    assert await bank_pool.fetchval("SELECT count(body) FROM part2_work") == 3
    assert await bank_pool.fetchval("SELECT score FROM part2_grades WHERE revision=2") == 2


async def test_daily_limit_and_unreadable_grade(bank_pool):
    bank = Part2Training(bank_pool)
    s = Settings(oge_grading_daily_user_limit=1, oge_grading_monthly_budget_usd=1)
    issue = await bank.open(1, 20)
    assert await bank.append(1, issue, 1, 301, None, "photo", "album") == "saved"
    assert (await reserve(bank_pool, s, 1, issue, 1))[1]
    result = Assessment.model_validate(
        {
            **VALID,
            "status": "unreadable",
            "score": None,
            "needs_review": True,
            "criterion_evidence": [],
        }
    )
    await finish(
        bank_pool, s, issue, 1, Grade(result, 10, 10, "demo", Decimal("0.00012")), dispatched=True
    )
    assert await bank.append(1, issue, 2, 302, None, "late photo", "album") == "stale"
    assert await bank.append(1, issue, 2, 303, "новая версия", None) == "saved"
    assert (await reserve(bank_pool, s, 1, issue, 2))[0].startswith("Дневной")
    row = await bank_pool.fetchrow("SELECT status,score FROM part2_grades")
    assert tuple(row.values()) == ("unreadable", None)

    await bank_pool.execute("UPDATE part2_work SET created_at=now()-interval '8 days'")
    await expire_work(bank_pool)
    expired = await bank_pool.fetchrow("SELECT * FROM part2_work WHERE message_id=301")
    assert expired["photo"] is None and expired["photo_expired"]
    assert (
        await bank_pool.fetchval("SELECT body FROM part2_work WHERE message_id=303")
        == "новая версия"
    )


async def test_full_input_limit_includes_schema_and_images_before_generation():
    from app.part2_grading import InputLimit, check_size

    def count_only(request):
        assert request.url.path.endswith("/responses/input_tokens")
        data = json.loads(request.content)
        assert data["text"]["format"]["strict"] and data["instructions"]
        assert data["input"][1]["content"][1]["type"] == "input_image"
        return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 30001})

    card = dict(
        statement="x=1",
        reference_solution="x=1",
        answer_or_claim="1",
        rubric={"kind": "atlas_training_rubric", "levels": {}},
        visuals=[],
    )
    async with AsyncOpenAI(
        api_key="mock", http_client=httpx.AsyncClient(transport=httpx.MockTransport(count_only))
    ) as client:
        with pytest.raises(InputLimit):
            await check_size(client, Settings(), inputs(card, [], ["работа"], [b"image"]))


async def test_api_test_and_student_share_atomic_limit(bank_pool):
    from app.persistence.part2_grades import budget_usage, reserve_test

    s = Settings(oge_grading_monthly_budget_usd=Decimal("0.10"))
    bank = Part2Training(bank_pool)
    issue = await bank.open(1, 20)
    await bank.append(1, issue, 1, 22, "решение", None)
    test_notice, (notice, _) = await asyncio.gather(
        reserve_test(bank_pool, s, 2, 14), reserve(bank_pool, s, 1, issue, 1)
    )
    assert bool(test_notice) != bool(notice)
    assert (await budget_usage(bank_pool, 1))["held"] == Decimal("0.09548")
    await bank_pool.execute("UPDATE part2_api_tests SET created_at=now()-interval '2 months'")
    await bank_pool.execute("UPDATE part2_grades SET created_at=now()-interval '2 months'")
    assert await reserve_test(bank_pool, s, 2, 15)
    assert await reserve_test(
        bank_pool, Settings(oge_grading_request_budget_usd=Decimal(".05")), 2, 16
    )


async def test_student_and_diagnostic_share_inflight_and_monthly_limits(bank_pool):
    from app.persistence.part2_grades import budget_usage, mark_dispatched, reserve_test

    bank = Part2Training(bank_pool)
    s = Settings()
    issue = await bank.open(1, 20)
    assert await bank.append(1, issue, 1, 200, "решение", None) == "saved"
    assert await reserve_test(bank_pool, s, 1, 199) == ""
    assert (await reserve(bank_pool, s, 1, issue, 1))[0].startswith("Одна проверка")
    await bank_pool.execute(
        "UPDATE part2_api_tests SET created_at=now()-interval '2 minutes' WHERE owner=1"
    )
    await mark_dispatched(bank_pool, 1, 199, diagnostic=True)
    await bank_pool.execute("UPDATE part2_api_tests SET status='graded',cost_usd=0.001")
    assert (await reserve(bank_pool, s, 1, issue, 1))[0].startswith("Между")
    await bank_pool.execute("UPDATE part2_api_tests SET dispatched_at=now()-interval '21 seconds'")
    assert (await reserve(bank_pool, s, 1, issue, 1))[1]
    assert (await budget_usage(bank_pool, 1))["monthly"] == 2
    await finish(bank_pool, s, issue, 1, None, dispatched=False)
    await bank_pool.execute(
        """INSERT INTO part2_api_tests(owner,confirmation,created_at,status,cost_usd,
           model,reserved_usd)
        SELECT 1, n, date_trunc('month',now(),'UTC'),'graded',0,'gpt-6.1-terra',0
        FROM generate_series(1,148) n"""
    )
    usage = await budget_usage(bank_pool, 1)
    assert usage["monthly"] >= 150
    assert (await reserve_test(bank_pool, s, 1, 201)).startswith("Месячный")
