"""Shared control labels and short, local feedback for bop."""
from typing import Literal

Action = Literal["hint", "solution", "skip", "similar", "next", "data", "menu", "progress"]
Reaction = Literal["start", "correct", "wrong", "corrected", "review", "analog", "series", "done"]

LABELS: dict[Action, str] = {
    "hint": "💡 Подсказка",
    "solution": "📘 Разбор",
    "skip": "⏭ Пропустить",
    "similar": "🔁 Похожее",
    "next": "➡ Дальше",
    "data": "📷 Схема / данные",
    "menu": "↩ В меню",
    "progress": "📊 Мой прогресс",
}

REPLIES: dict[Reaction, tuple[str, ...]] = {
    "start": ("Выбери тренировку.", "С чего начнём?"),
    "correct": ("Верно! Ответ засчитан.", "Отлично, верно! Ответ засчитан."),
    "wrong": ("Пока неверно. Попробуй ещё раз.", "Пока не получилось. Попробуй ещё раз."),
    "corrected": ("Вот теперь верно!", "Исправил ответ. Верно!"),
    "review": ("Давай разберёмся.", "Посмотри, как решить эту задачу."),
    "analog": ("С похожей задачей ты справился сам!", "Этот похожий вариант ты решил сам."),
    "series": ("Снова справился сам после перерыва.", "После перерыва задача снова получилась."),
    "done": ("Тренировка завершена!", "Тренировка завершена. Увидимся!"),
}


def reply(role: Reaction, event: int | None = None) -> str:
    variants = REPLIES[role]
    return variants[(event or 0) % len(variants)]
