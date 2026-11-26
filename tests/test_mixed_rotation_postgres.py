import json
import os
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.types import BufferedInputFile, CallbackQuery, Chat, Message, User

from app.adaptive.session import Session
from app.bot import adaptive
from app.config import get_settings
from app.persistence.repository import PostgresRepository
from scripts.story_stabilization_gallery import OfflineCaptureSession

REPORT = Path("reports/navigation-rotation")


def _publish(name: str, payload: object) -> None:
    if os.getenv("REPORT_MIXED_ROTATION") != "1":
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def _candidate(family: str, number: int) -> dict[str, object]:
    return {
        "problem_id": str(uuid4()), "family_id": family, "number": number,
        "fingerprint": str(uuid4()), "generator_version": "rotation-simulation", "condition": "1+1",
        "correct_answer": "2", "hints": ["Сложите числа."], "solution": ["1 + 1 = 2."],
    }


class MixedCaptureSession(OfflineCaptureSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.message_id += 1
        files = {}
        body = {}
        for key, value in method.model_dump(warnings=False).items():
            if (prepared := self.prepare_value(value, bot=bot, files=files)) is not None:
                body[key] = prepared
        attachments = {}
        for key, file in files.items():
            assert isinstance(file, BufferedInputFile)
            path = f"mixed-media-{sha256(file.data).hexdigest()[:16]}.png"
            attachments[key] = {"path": path, "filename": file.filename, "bytes": len(file.data)}
            if os.getenv("REPORT_MIXED_ROTATION") == "1":
                REPORT.mkdir(parents=True, exist_ok=True)
                (REPORT / path).write_bytes(file.data)
        self.calls.append({
            "method": method.__api_method__, "body": body, "attachments": attachments,
        })
        return Message(
            message_id=self.message_id, date=datetime.now(UTC), chat=Chat(id=1, type="private"),
        ).as_(bot)


async def _start(store: Session, catalog: dict[str, int], seed: str) -> None:
    await store.start([], strategy="mixed", scope={"plan_seed": seed}, mixed_catalog=catalog)


async def _issue(store: Session, catalog: dict[str, int], prompt: int | None):
    row = await store.current()
    scope = adaptive._scope(row)
    number, families, tail = await store.mixed_choices(row, catalog, scope)
    family = families[0]
    plan = json.loads(row["plan"])
    plan[row["position"]] = family
    assert await store.refresh(row, plan)
    assert await store.save(row, family, _candidate(family, number), mixed_claim=(number, tail))
    issued = await store.current()
    if prompt is not None:
        assert await store.set_prompt(store.learner, str(issued["problem"]), prompt)
    return number, family, issued["problem"]


@pytest.mark.mass
async def test_mixed_number_and_family_distribution_over_100_trainings(bank_pool):
    catalog = adaptive.catalog()
    assert set(catalog.values()) == set(range(1, 20))
    repository = PostgresRepository(bank_pool)
    store = Session(repository, 1)
    trainings = []
    number_counts: Counter[int] = Counter()
    family_counts: Counter[str] = Counter()
    for batch in range(100):
        await _start(store, catalog, f"rotation-acceptance-{batch}")
        sequence = []
        families = []
        for position in range(5):
            if batch == 0 and position == 2:
                store = Session(PostgresRepository(bank_pool), 1)
                await store.start([])
            number, family, problem = await _issue(store, catalog, batch * 5 + position + 10)
            sequence.append(number)
            families.append(family)
            number_counts[number] += 1
            family_counts[family] += 1
            expected = "completed_skip" if position == 4 else "skip"
            assert await store.act(problem, None, "skip") == expected
            if position < 4:
                assert await store.act(problem, None, "next") == "next"
        assert len(set(sequence)) == 5
        trainings.append({"training": batch + 1, "numbers": sequence, "families": families})
    flattened = [number for training in trainings for number in training["numbers"]]
    for index in range(0, len(flattened), 19):
        chunk = flattened[index:index + 19]
        assert len(set(chunk)) == len(chunk)
    assert max(number_counts.values()) - min(number_counts.values()) == 1
    for number in number_counts:
        counts = [family_counts[family] for family, value in catalog.items() if value == number]
        assert max(counts) - min(counts) <= 1
    _publish("mixed-100-trainings.json", {
        "simulation": "PostgreSQL, actual public catalogue and persistent selector",
        "generation": "synthetic unique snapshots isolate number and family selection",
        "restart": {"training": 1, "before_position": 3},
        "completed_cycles": len(flattened) // 19,
        "first_cycle": flattened[:19],
        "first_four_trainings": trainings[:4],
        "training_sequences": trainings,
        "number_distribution": dict(sorted(number_counts.items())),
        "family_distribution": {family: family_counts[family] for family in sorted(catalog)},
    })


async def test_mixed_delivered_once_similar_and_abandoned_do_not_consume_number(bank_pool):
    catalog = adaptive.catalog()
    repository = PostgresRepository(bank_pool)
    store = Session(repository, 1)
    await _start(store, catalog, "resume-first")
    number, family, problem = await _issue(store, catalog, 1)
    before = adaptive._scope(await store.current())
    assert before["mixed_batch"] == [number]
    assert await store.act(problem, 1, "menu") == "paused"
    restarted = Session(PostgresRepository(bank_pool), 1)
    await restarted.start([])
    assert (await restarted.current())["problem"] == problem
    assert await restarted.set_prompt(1, str(problem), 2)
    assert adaptive._scope(await restarted.current()) == before
    assert await restarted.act(problem, 2, "skip") == "skip"
    row = await restarted.current()
    assert await restarted.choose_similar(row["id"], 0, problem, prompt=2) == "next"
    row = await restarted.current()
    similar = _candidate(family, number)
    assert await restarted.save(row, family, similar)
    assert await restarted.set_prompt(1, str(similar["problem_id"]), 3)
    assert adaptive._scope(await restarted.current()) == before
    row = await restarted.current()
    assert await restarted.act(row["problem"], 3, "skip") == "skip"
    assert await restarted.act(row["problem"], 3, "next") == "next"
    unpresented, _, pending = await _issue(restarted, catalog, None)
    assert unpresented == before["mixed_rotation"]["remaining"][0]
    assert await restarted.act(pending, None, "finish") == "finished"
    await _start(restarted, catalog, "resume-second")
    other = Session(repository, 2)
    await _start(other, catalog, "independent-user")
    assert adaptive._scope(await other.current())["mixed_rotation"] == {"seed": "independent-user"}
    next_number, _, _ = await _issue(restarted, catalog, 4)
    assert next_number == unpresented


async def test_mixed_dispatch_retries_same_number_and_emits_real_payloads(bank_pool, monkeypatch):
    monkeypatch.setenv("OGE_ADAPTIVE_ENABLED", "true")
    get_settings.cache_clear()
    repository = PostgresRepository(bank_pool)
    learner = User(id=1, is_bot=False, first_name="Синтетический ученик")
    transport = MixedCaptureSession("mixed-rotation")
    bot = Bot("123456:OFFLINE", session=transport)
    chat = Chat(id=1, type="private")
    incoming = Message(
        message_id=2000, date=datetime.now(UTC), chat=chat, from_user=learner,
    ).as_(bot)
    store = Session(repository, 1)
    monkeypatch.setattr(adaptive.secrets, "token_hex", lambda _: "mixed-dispatch")

    def fail(*_):
        raise OSError("simulated transient generation failure")

    generate = adaptive.generate
    monkeypatch.setattr(adaptive, "generate", fail)
    await adaptive.start(incoming, repository, strategy="mixed")
    failed = await store.current()
    assert failed["problem"] is None
    scope = adaptive._scope(failed)
    assert scope["mixed_rotation"] == {"seed": "mixed-dispatch"}
    first_number, _, _ = await store.mixed_choices(failed, adaptive.catalog(), scope)
    failed_payload = list(transport.calls)
    transport.calls.clear()
    monkeypatch.setattr(adaptive, "generate", generate)
    await adaptive.callback(
        CallbackQuery(
            id="retry", from_user=learner, chat_instance="rotation",
            data=f"ad:retry:{failed['id']}.{failed['position']}",
            message=Message(
                message_id=failed["prompt"], date=datetime.now(UTC), chat=chat,
            ).as_(bot),
        ).as_(bot),
        repository,
    )
    first = await store.current()
    assert first["problem"] is not None
    assert adaptive.problem_data(first)["number"] == first_number
    initial = list(transport.calls)
    sequence = [first_number]
    terminal = []
    transitions = []
    try:
        for position in range(5):
            if position:
                sequence.append(adaptive.problem_data(await store.current())["number"])
            for action in (("skip",) if position == 4 else ("skip", "next")):
                row = await store.current()
                assert row is not None and row["prompt"] is not None
                anchor = Message(
                    message_id=row["prompt"], date=datetime.now(UTC), chat=chat,
                ).as_(bot)
                callback = CallbackQuery(
                    id=f"{position}:{action}", from_user=learner, chat_instance="rotation",
                    data=f"ad:{action}:{row['problem']}", message=anchor,
                ).as_(bot)
                transport.calls.clear()
                await adaptive.callback(callback, repository)
                if position == 4:
                    terminal = list(transport.calls)
                else:
                    transitions.append({
                        "position": position + 1, "action": action, "calls": list(transport.calls),
                    })
        assert len(set(sequence)) == 5
        assert await store.current() is None
        assert any("Тренировка завершена" in str(call) for call in terminal)
        _publish("mixed-bot-api.json", {
            "case": "PG-backed dispatcher, actual candidate generation after transient error",
            "numbers": sequence, "technical_failure": failed_payload,
            "initial": initial, "transitions": transitions, "terminal": terminal,
        })
    finally:
        await bot.session.close()
        get_settings.cache_clear()
