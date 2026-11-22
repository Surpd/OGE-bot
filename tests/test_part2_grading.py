import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.bot.part2_check import grading_reply
from app.config import Settings
from app.part2_grading import (
    INSTRUCTIONS,
    PROMPT_VERSION,
    Assessment,
    Grade,
    assess,
    clean_photo,
    inputs,
)
from app.persistence.part2_bank import load_bank
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


@pytest.mark.parametrize("score", [0, 1, 2])
def test_grading_reply_only_shows_corrections_below_full_score(score):
    assessment = Assessment.model_validate(
        {**VALID, "score": score, "errors": ["Ошибка"], "next_step": "Проверь вычисления"}
    )
    reply = grading_reply(assessment, "atlas_training_rubric")

    assert f"Оценка: {score} из 2 баллов (предварительная)" in reply
    assert "Что правильно" in reply
    assert "Проверил ОДЗ" in reply
    assert ("Где ошибка" in reply) == (score < 2)
    assert ("Как исправить" in reply) == (score < 2)
    assert ("Проверь вычисления" in reply) == (score < 2)


@pytest.mark.parametrize(
    "status, notice",
    [
        ("unreadable", "Не удалось прочитать решение."),
        ("uncertain", "Не удалось уверенно оценить решение."),
        ("error", "Проверка не завершилась."),
    ],
)
def test_grading_reply_distinguishes_unscored_outcomes(status, notice):
    assessment = Assessment.model_validate(
        {**VALID, "status": status, "score": None, "needs_review": True, "criterion_evidence": []}
    )
    reply = grading_reply(assessment, "atlas_training_rubric")

    assert reply.startswith(f"{notice} Балл не выставлен.")
    assert "из 2 баллов" not in reply
    assert "Проверить решение" not in reply  # Historical results have no action buttons.


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


GRADING_FIXTURES = Path(__file__).parent / "fixtures" / "part2-grading"
RATIONAL_CASES = [
    row
    for row in json.loads((GRADING_FIXTURES / "cases.json").read_text(encoding="utf-8"))
    if row["id"].startswith("rational-20-")
]


def test_rational_calibration_preserves_exact_card_rules():
    _, bank = load_bank()
    calibrated = 0
    for _, _, payload, _ in bank:
        card = json.loads(payload)
        request = inputs(card, [], [], [])
        context = json.loads(request[0]["content"][0]["text"])
        scoped = card["number"] == 20 and card["subtype_id"] == "OGE20-rational-inequality"
        assert ("grading_calibration" in context) == scoped
        assert context["rubric"]["levels"] == card["rubric"]["levels"]
        calibrated += scoped
    assert calibrated == 6
    assert PROMPT_VERSION == "oge-written-3"


@pytest.mark.parametrize("case", RATIONAL_CASES, ids=[case["id"] for case in RATIONAL_CASES])
async def test_rational_calibration_request_and_mock_assessment(case):
    # Human-labeled cases for an offline comparison. The SDK response here is
    # mocked to test transport and validation, not the model's scoring accuracy.
    _, bank = load_bank()
    card = next(json.loads(raw) for task_id, _, raw, _ in bank if task_id == case["task_id"])
    score = case["expected_score"]
    status = case["expected_status"]
    evidence = (
        [{"criterion": card["rubric"]["levels"][str(score)]["rule"],
          "student_evidence": case["case"]}]
        if score is not None
        else []
    )
    report = {**VALID, "status": status, "score": score, "criterion_evidence": evidence,
              "needs_review": score is None}
    captures = []

    def handler(request):
        captures.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline_rational",
            "object": "response",
            "status": "completed",
            "model": "gpt-6.1-terra",
            "output": [{"type": "message", "id": "msg_offline", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(report),
                                     "annotations": []}]}],
            "usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160,
                      "input_tokens_details": {"cached_tokens": 0}},
        })

    photos = [clean_photo((GRADING_FIXTURES / case["image"]).read_bytes())] if case["image"] else []
    request = inputs(card, [], [case["body"]], photos)
    async with AsyncOpenAI(
        api_key="mock", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as client:
        result = await assess(client, Settings(), card, request)
    sent = captures[0]
    context = json.loads(sent["input"][0]["content"][0]["text"])
    assert sent["instructions"] == INSTRUCTIONS
    assert "grading_calibration" in sent["instructions"]
    assert context["rubric"] == {key: card["rubric"][key] for key in ("kind", "levels")}
    assert len(context["grading_calibration"]) == 4
    student = sent["input"][1]["content"]
    assert student[0]["text"] == "Работа ученика:\n" + case["body"]
    if photos:
        assert student[1]["image_url"].startswith("data:image/jpeg;base64,")
        assert student[1]["detail"] == "high"
    assert (result.assessment.status, result.assessment.score) == (status, score)


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
        assert await bank.append(owner, issue, 1, 80, "работа", "photo") == "saved"
    reservations = await asyncio.gather(
        *(reserve(bank_pool, s, owner, issue, 1) for owner, issue in enumerate(ids, 1))
    )
    assert sum(bool(work) for _, work in reservations) == 1
    winner = next(i for i, r in enumerate(reservations) if r[1])
    issue, owner = ids[winner], winner + 1
    assert not (await reserve(bank_pool, s, owner, issue, 1))[1]
    await finish(bank_pool, s, issue, 1, None, dispatched=True)
    assert await bank.append(owner, issue, 2, 81, "исправление", "photo") == "saved"
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
    assert await bank.append(1, issue, 1, 301, None, "photo") == "saved"
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
    assert await bank.append(1, issue, 2, 303, "новая версия", "photo") == "saved"
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
    await bank.append(1, issue, 1, 22, None, "photo")
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
    assert await bank.append(1, issue, 1, 200, None, "photo") == "saved"
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


async def test_legacy_text_draft_requires_photo_before_reservation(bank_pool):
    bank = Part2Training(bank_pool)
    issue = await bank.open(1, 20)
    await bank.append(1, issue, 1, 601, "Старое письменное решение", None)
    notice, work = await reserve(bank_pool, Settings(), 1, issue, 1)
    assert "фото" in notice and not work
    assert await bank_pool.fetchval("SELECT count(*) FROM part2_grades") == 0
    assert await bank_pool.fetchval("SELECT body FROM part2_work") == "Старое письменное решение"
    await bank.append(1, issue, 1, 602, None, "new-photo")
    assert (await reserve(bank_pool, Settings(), 1, issue, 1))[1]
