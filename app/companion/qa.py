"""A small exact-card desk, using the student's replay and presentation code."""

import asyncio
import copy
import secrets
from typing import Any
from uuid import UUID, uuid4

from aiogram.types import InlineKeyboardMarkup, Message

from app.bot import error_replay, part2
from app.bot.presentation import send_text
from app.bot.scenario_training import STORY_NAMES, public_registry
from app.companion.catalog import STARTERS, bank_cards, fixture, generate, identity
from app.companion.photo import NOTICE, simulate
from app.math.scenario_engine import PracticeMode
from app.persistence.error_replay import (
    ErrorReplayRepository,
    ReplaySource,
    _scenario_question,
    load_original_source,
)
from app.persistence.repository import MemoryRepository, Repository
from app.persistence.rotation_history import enabled
from app.persistence.training_insights import family_name, training_insights


class PresentationSandbox(MemoryRepository):
    def __init__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self.qa_state = state
        self.png_templates = set(state.get("png_templates", []))

    async def remember_png_template(self, template_id: str) -> None:
        await super().remember_png_template(template_id)
        self.qa_state["png_templates"] = sorted(self.png_templates)


class Desk:
    def __init__(self, state: dict[str, Any], repository: Repository, owner: int) -> None:
        self.state, self.repository, self.owner = state, repository, owner
        # Only this disposable repository reaches presentation and replay writes.
        self.sandbox = PresentationSandbox(state)
        self.replays = ErrorReplayRepository(self.sandbox)
        if state.get("replay"):
            row = state["replay"]
            self.sandbox._training_error_replays = {  # type: ignore[attr-defined]
                (owner, "ordinary", row["source_id"], 0): row,
            }

    async def prepare(self) -> None:
        await self.sandbox.save_user_state(self.owner, "error_replay")
        await self.sandbox.set_math_display(self.owner, self.state.get("display", "auto"))

    def keyboard(self, rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
        revision = secrets.token_hex(4)
        self.state["revision"] = revision
        self.state["actions"] = [action for row in rows for _, action in row]
        return part2.keyboard(
            [[(label, f"qa:{revision}:{action}") for label, action in row] for row in rows]
        )

    async def say(self, message: Message, text: str, rows: list[list[tuple[str, str]]]) -> None:
        self.state["screen"] = "menu"
        sent = await send_text(
            message,
            self.sandbox,
            text,
            user_id_override=self.owner,
            reply_markup=self.keyboard(rows),
        )
        self.state["menu"] = sent.message_id

    async def home(self, message: Message) -> None:
        self.state["active"] = True
        self.state.pop("pending", None)
        await self.say(
            message,
            "Тестовый бот · точные проверки\n"
            "Выберите короткую подборку или нужный вариант. "
            "Зачёт и история ученика не меняются.\n" + NOTICE,
            [[(title, f"fixture:{i}")] for i, title in enumerate(STARTERS)]
            + ([[("Последний точный вариант", "repeat")]] if self.state.get("card") else [])
            + [
                [("По номеру / типу", "numbers"), ("История тестов", "history:0")],
                [("Найти карточку / ID", "id"), ("Как ученик", "exit")],
                [("Недавние точные карточки", "archive")],
                *([[("↩ Админ-панель", "admin")]] if self.state.get("admin_enabled") else []),
                [("Сбросить тестовую сессию", "reset")],
            ],
        )

    async def numbers(self, message: Message) -> None:
        await self.say(
            message,
            "Выберите номер. №1–5 — сюжет и позиция; №6–19 — семейство; №20–25 — карточка банка.",
            [
                [(str(n), f"number:{n}:0") for n in range(start, min(start + 5, 26))]
                for start in range(1, 26, 5)
            ]
            + [[("К проверкам", "home")]],
        )

    async def choices(self, message: Message, number: int, page: int) -> None:
        if number <= 5:
            items = [
                (STORY_NAMES.get(story, story), story)
                for story in public_registry().available_stories(PracticeMode.SINGLE, number)
            ]
        elif number <= 19:
            items = [(family_name(f), f) for f in enabled(number)]
        else:
            items = [
                (f"{c['task_id'].removeprefix('oge-part2-')} · {c['statement'][:45]}", c["task_id"])
                for c in bank_cards()
                if c["number"] == number
            ]
        page = max(0, min(page, max(0, (len(items) - 1) // 6)))
        selected = items[page * 6 : page * 6 + 6]
        self.state["choices"] = [value for _, value in selected]
        self.state["number"] = number
        rows = [[(label, f"choose:{i}")] for i, (label, _) in enumerate(selected)]
        arrows = []
        if page:
            arrows.append(("←", f"number:{number}:{page - 1}"))
        if (page + 1) * 6 < len(items):
            arrows.append(("→", f"number:{number}:{page + 1}"))
        if arrows:
            rows.append(arrows)
        await self.say(
            message,
            f"№{number} · страница {page + 1}",
            rows + [[("К номерам", "numbers"), ("Выйти", "exit")]],
        )

    def source(self) -> ReplaySource:
        card = self.state["card"]
        return ReplaySource(
            "ordinary",
            UUID(self.state["source_id"]),
            0,
            card["number"],
            card["snapshot"],
            card.get("scenario"),
        )

    def controls(self) -> InlineKeyboardMarkup:
        rows = [
            [("Подсказка", "hint"), ("Разбор", "solution")],
            [("Повторить этот вариант", "repeat"), ("Повтор ошибки", "mistake")],
            [("Rich / авто", "display:auto"), ("PNG", "display:png")],
        ]
        if self.state["card"].get("scenario"):
            rows += [[(f"№{n} этого комплекта", f"position:{n}") for n in range(1, 6)]]
        if self.state["card"]["number"] >= 20:
            rows += [
                [("Имитировать результат", "photo:ok"), ("Имитировать ошибку", "photo:error")],
                [("Убрать фото", "remove")],
            ]
        rows += [
            [("Следующая проверка", "next"), ("Выбрать другой", "home")],
            [("Диагностика", "diagnostic"), ("Выйти", "exit")],
        ]
        return self.keyboard(rows)

    async def open(self, message: Message, card: dict[str, Any]) -> None:
        card = copy.deepcopy(card)
        key = identity(card)
        archive = self.state.setdefault("archive", {})
        order = self.state.setdefault("archive_order", list(archive))
        if key in order:
            order.remove(key)
        order.append(key)
        archive[key] = card
        # JSONB sorts object keys; recency must be persisted as an explicit array.
        while len(order) > 12:
            archive.pop(order.pop(0), None)
        self.state.update(card=card, card_id=key, source_id=str(uuid4()), photo=False)
        self.state.pop("pending", None)
        self.sandbox._training_error_replays = {}  # type: ignore[attr-defined]
        self.state["replay"] = await self.replays.start(self.owner, self.source())
        # Keep the mutable row used by the existing state machine.
        self.state["replay"] = next(iter(self.sandbox._training_error_replays.values()))  # type: ignore[attr-defined]
        await self.render(message)

    async def render(self, message: Message) -> None:
        self.state["screen"] = "card"
        card = self.state["card"]
        snapshot, number = card["snapshot"], card["number"]
        await message.answer(
            f"QA · №{number} · {snapshot.get('family_id', snapshot.get('task_id', ''))}\n"
            f"Версия: {snapshot.get('generator_version', snapshot.get('content_version'))}; "
            f"seed: {snapshot.get('seed', snapshot.get('scenario_seed', 'нет'))}\n"
            f"ID: {self.state['card_id']}\n{card['note']}\n"
            "Проверяем: условие, данные, формулы, подсказку, разбор, ответ и повтор."
        )
        markup = self.controls()
        if number >= 20:
            sent = await part2.card_message(
                message,
                self.sandbox,
                self.owner,
                snapshot,
                "condition",
                part2.statement_text(snapshot, NOTICE),
                markup,
            )
            self.state["replay"]["prompt_message_id"] = sent.message_id
        else:
            source = self.source()
            materials = await asyncio.to_thread(error_replay._materials, source)
            await error_replay._render(
                message,
                self.sandbox,
                self.replays,
                self.state["replay"],
                source,
                user_id=self.owner,
                materials=materials,
                controls=markup,
            )
        self.state["menu"] = self.state["replay"]["prompt_message_id"]

    async def feedback(self, message: Message, text: str) -> None:
        card = self.state["card"]
        sent = await send_text(
            message,
            self.sandbox,
            text,
            user_id_override=self.owner,
            reply_markup=self.controls(),
            math_family=card["snapshot"],
            rich_with_navigation=True,
        )
        self.state["menu"] = sent.message_id

    async def history(self, message: Message, offset: int) -> None:
        results = await training_insights(self.repository, self.owner, f"history:{offset}")
        records = results["history"]
        self.state["history"] = [r["record_id"] for r in records]
        rows = [
            [(f"№{r['number']} · {family_name(r['family_id'])}", f"history_open:{i}")]
            for i, r in enumerate(records)
        ]
        arrows = []
        if offset:
            arrows.append(("←", f"history:{max(0, offset - 6)}"))
        if offset + 6 < results["page_total"]:
            arrows.append(("→", f"history:{offset + 6}"))
        if arrows:
            rows.append(arrows)
        await self.say(
            message,
            "Только ваши попытки №1–19 в изолированной тестовой схеме. "
            "Письменные работы доступны в обычном «Прогрессе». "
            "Чужие попытки и фотографии здесь не открываются.",
            rows + [[("К проверкам", "home"), ("Выйти", "exit")]],
        )

    async def action(self, message: Message, action: str) -> None:
        parts = action.split(":")
        if action != "diagnostic":
            self.state["last_step"] = action
        if action == "diagnostic":
            card = self.state.get("card", {})
            snapshot = card.get("snapshot", {})
            await self.feedback(
                message,
                f"QA diagnostic\nSHA={self.state.get('sha', 'local')}\n"
                f"number={card.get('number')}\n"
                f"type={snapshot.get('family_id', snapshot.get('task_id'))}\n"
                f"version={snapshot.get('generator_version', snapshot.get('content_version'))}\n"
                f"seed={snapshot.get('seed', snapshot.get('scenario_seed'))}\n"
                f"id={self.state.get('card_id')}\n"
                f"step={self.state.get('last_step', 'open')}\n"
                f"display={self.state.get('display', 'auto')}\n"
                "photo=simulation; acceptance=manual / known red №16",
            )
        elif parts[0] == "position":
            card = copy.deepcopy(self.state["card"])
            card["number"] = int(parts[1])
            card["snapshot"] = _scenario_question(card["scenario"], card["number"])
            await self.open(message, card)
        elif action == "reset":
            await self.say(
                message,
                "Сбросить только вашу тренировку в тестовом боте? "
                "Боевые данные не затрагиваются. Последние 12 точных снимков сохранятся.",
                [[("Сбросить", "reset_confirm"), ("Отмена", "home")]],
            )
        elif action == "archive":
            await self.say(
                message,
                "Последние точные снимки этого тестового бота:",
                [
                    [(f"№{card['number']} · {key}", f"arch:{key}")]
                    for key in reversed(
                        self.state.get("archive_order", list(self.state.get("archive", {})))
                    )
                    for card in [self.state["archive"][key]]
                ]
                + [[("К проверкам", "home")]],
            )
        elif parts[0] == "arch":
            await self.open(message, self.state["archive"][parts[1]])
        elif action == "home":
            await self.home(message)
        elif action == "numbers":
            await self.numbers(message)
        elif parts[0] == "number":
            await self.choices(message, int(parts[1]), int(parts[2]))
        elif parts[0] == "fixture" or action == "next":
            index = (
                int(parts[1]) if parts[0] == "fixture" else (self.state.get("starter", -1) + 1) % 4
            )
            self.state["starter"] = index
            await self.open(message, fixture(index))
        elif parts[0] == "choose":
            family = self.state["choices"][int(parts[1])]
            number = self.state["number"]
            if number >= 20:
                card = next(c for c in bank_cards() if c["task_id"] == family)
                await self.open(
                    message, {"number": number, "snapshot": card, "scenario": None, "note": NOTICE}
                )
            else:
                self.state["selected"] = family
                await self.say(
                    message,
                    f"№{number} · {family}",
                    [
                        [("Открыть вариант seed 0", "generate")],
                        [("Указать seed + версию", "seed")],
                        [("К номерам", "numbers")],
                    ],
                )
        elif action == "generate":
            card = await asyncio.to_thread(generate, self.state["number"], self.state["selected"])
            await self.open(message, card)
        elif action in {"seed", "id"}:
            self.state["pending"] = action
            text = (
                "Введите seed и точную версию через пробел, например: 19 oge16-circles-3. "
                "Без поддерживаемой версии точность восстановления не обещается."
                if action == "seed"
                else "Введите короткий QA ID, полный ID банковской карточки или её числовой "
                "ID (например, 438301). Хранятся последние 12 точных снимков. "
                "История содержит только ваши попытки в тестовом боте."
            )
            await self.say(message, text, [[("Отмена", "home"), ("Выйти", "exit")]])
        elif parts[0] == "history":
            await self.history(message, int(parts[1]))
        elif parts[0] == "history_open":
            source = await load_original_source(
                self.repository, self.owner, self.state["history"][int(parts[1])]
            )
            await self.open(
                message,
                {
                    "number": source.number,
                    "snapshot": source.snapshot,
                    "scenario": source.scenario_snapshot,
                    "note": "Точный исходный snapshot вашей тестовой попытки. "
                    "Историческое содержание не означает успешную приёмку.",
                },
            )
        elif action in {"repeat", "mistake"}:
            if action == "mistake" and not any(
                not a["is_correct"] for a in self.state["replay"].get("attempts", [])
            ):
                await self.feedback(message, "Сначала допустите ошибку в этой проверке.")
            else:
                await self.open(message, self.state["card"])
        elif parts[0] == "display":
            self.state["display"] = parts[1]
            await self.sandbox.set_math_display(self.owner, parts[1])
            # Showing the exact condition again does not reset attempts/hints.
            if self.state["replay"]["status"] == "active":
                await self.render(message)
            else:
                await self.feedback(message, "Вид формул выбран. Нажмите «Повторить этот вариант».")
        elif action in {"hint", "solution"}:
            card = self.state["card"]
            if card["number"] >= 20:
                text = (
                    part2.solution_text(card["snapshot"])
                    if action == "solution"
                    else str(card["snapshot"].get("hints", ["Подсказки нет"])[0])
                )
                sent = await part2.card_message(
                    message,
                    self.sandbox,
                    self.owner,
                    card["snapshot"],
                    action,
                    text,
                    self.controls(),
                )
                self.state["menu"] = sent.message_id
            else:
                action_text = await self.replays.action(
                    self.owner, UUID(self.state["replay"]["id"]), action, card["snapshot"]
                )
                await self.feedback(
                    message,
                    action_text or "Действие недоступно: подсказки или попытка закончились.",
                )
        elif action == "remove":
            self.state["photo"] = False
            await self.feedback(message, "Тестовое вложение убрано.")
        elif parts[0] == "photo":
            if not self.state.get("photo"):
                await self.feedback(message, "Пришлите одно тестовое фото ответом на условие.")
            else:
                markup = self.controls()
                sent = await simulate(
                    message, self.sandbox, self.owner, markup, error=parts[1] == "error"
                )
                self.state["menu"] = sent.message_id

    async def input(self, message: Message) -> None:
        pending = self.state.get("pending")
        if pending == "id":
            query = (message.text or "").strip().lower()
            card = self.state.get("archive", {}).get(query)
            if card is None:
                matches = [
                    c
                    for c in bank_cards()
                    if c["task_id"].lower() == query or c["task_id"].rsplit("-", 1)[-1] == query
                ]
                if len(matches) != 1:
                    raise ValueError("Exact ID unavailable")
                snap = matches[0]
                card = {
                    "number": snap["number"],
                    "snapshot": snap,
                    "scenario": None,
                    "note": NOTICE,
                }
            await self.open(message, card)
        elif pending == "seed":
            seed, version = (message.text or "").split()
            card = await asyncio.to_thread(
                generate, self.state["number"], self.state["selected"], int(seed), version
            )
            await self.open(message, card)
        elif "card" not in self.state or self.state.get("screen") != "card":
            await self.home(message)
        elif self.state["card"]["number"] >= 20:
            prompt = self.state["replay"].get("prompt_message_id")
            if (
                not message.photo
                or message.media_group_id
                or not message.reply_to_message
                or message.reply_to_message.message_id != prompt
                or message.message_id <= prompt
                or not message.photo[-1].file_size
                or message.photo[-1].file_size > 4_000_000
            ):
                await self.feedback(
                    message,
                    "Нужно одно тестовое фото до 4 МБ ответом на текущее условие. "
                    "Альбом и Reply к старому заданию не принимаются.",
                )
                return
            self.state["photo"] = True  # Never retain file_id, bytes or user photograph.
            await self.feedback(message, "Тестовое фото принято. " + NOTICE)
        elif message.text:
            source = self.source()
            correct = error_replay._accepts(source, message.text)
            if correct is None:
                await self.feedback(message, "Введите ответ в формате условия; попытка не списана.")
                return
            result = await self.replays.record_attempt(
                self.owner,
                UUID(self.state["replay"]["id"]),
                message.text,
                correct,
                message.message_id,
                message.reply_to_message.message_id if message.reply_to_message else None,
            )
            if result is None or result["event"] != "accepted":
                await self.feedback(
                    message, "Ответ не принят: старая, повторная или завершённая попытка."
                )
                return
            if result["status"] == "active":
                text = "Пока неверно. Попробуйте ещё раз."
            elif result["status"] == "solved":
                text = "Ответ совпал с сохранённым эталоном. Это НЕ зелёная приёмка карточки."
            else:
                steps = source.snapshot.get("solution_steps", source.snapshot.get("solution", []))
                text = (
                    f"Попытки закончились. Ответ: {source.correct_answer}\n\nРазбор\n"
                    + "\n".join(map(str, steps))
                    if isinstance(steps, list)
                    else "Разбор недоступен"
                )
            await self.feedback(message, text)
