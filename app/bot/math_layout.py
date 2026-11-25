"""Presentation of owned training headings; never changes formula tokens."""

import re
from collections.abc import Callable, Iterable
from typing import Literal

from app.bot.explicit_math import formulas
from app.bot.math_notation import math_spans

HEADING = re.compile(
    r"^(Персональная · [^\n]+|Настройки$|Повтор исходной задачи №\d+|"
    r"(?:.+ · )?Задание №[^\n]+|Мой прогресс[^\n]*|Подробнее о номере|"
    r"Практика №[^\n]*|Оценка:[^\n]*|Что правильно:|Где ошибка:|Как исправить:|"
    r"Почему именно [^:]+:|Оценка не выставлена\.|Письменные работы|"
    r"История(?: · №\d+)?|Мои ошибки(?: · №\d+)?|"
    r"№\d+ · [^\n]+|Исходное условие:|Результат:|Попытки:|По семействам:|"
    r"Разбор(?: \(самостоятельное решение не засчитывается\))?:|"
    r"Подсказка(?: №\d+)?:|Ответ:|Правильный ответ:|Правильный вариант:)"
)

Role = Literal[
    "title", "position", "context", "question", "instruction", "reaction",
    "hint", "solution", "steps", "answer", "stats", "section", "recommendation",
]
EMPHASIS = {"title", "position", "hint", "solution", "answer", "section"}


class TrainingMessage(str):
    """Text-compatible training blocks. Roles travel with them through presentation."""

    blocks: tuple[tuple[Role, str], ...]

    def __new__(cls, *blocks: tuple[Role, str]) -> "TrainingMessage":
        visible = tuple((role, text) for role, text in blocks if text)
        message = super().__new__(cls, "\n\n".join(text for _, text in visible))
        message.blocks = visible
        return message

    def transform(self, render: Callable[[str], str]) -> "TrainingMessage":
        return TrainingMessage(*((role, render(body)) for role, body in self.blocks))

    def has_role(self, *roles: Role) -> bool:
        return any(role in roles for role, _ in self.blocks)

    def headings(self) -> frozenset[str]:
        return frozenset(
            line for role, body in self.blocks if role in EMPHASIS for line in body.splitlines()
        )


def heading_for(line: str, headings: frozenset[str] | None) -> str:
    if headings is not None:
        if line not in headings:
            return ""
        return "Ответ:" if line.startswith("Ответ:") else line
    match = HEADING.match(line)
    return match.group(0) if match else ""


def question_message(
    title: str, question: str, detail: str = "", *, position: str = "",
) -> TrainingMessage:
    return TrainingMessage(
        ("title", title), ("position", position), ("question", question), ("instruction", detail),
    )


def solution_message(steps: Iterable[str], answer: str, intro: str = "") -> TrainingMessage:
    return TrainingMessage(
        ("reaction", intro), ("solution", "Разбор:"),
        ("steps", "\n\n".join(steps)), ("answer", f"Ответ: {answer}" if answer else ""),
    )


def action_prefix(line: str) -> str | None:
    action, separator, _ = line.partition(":")
    if separator and any(start <= len(action) < end for start, end, _ in formulas(line)):
        return None
    description = action
    if len(action) > 2 and action[0].isdigit() and action[1] in ".)":
        description = action[2:]
    if separator and not any(span.latex is not None for span in math_spans(description)):
        return action + ":"
    return None


def layout_text(source: str) -> str:
    instruction = "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой."
    if source.startswith("Задание №") and source.endswith(instruction):
        source = source.removesuffix(instruction).rstrip()
    lines = source.split("\n")
    final_answer = None
    if lines and lines[0].startswith("Вторая попытка неверна."):
        for label in ("Правильный ответ:", "Правильный вариант:", "Ответ:"):
            if label in lines[0]:
                feedback, answer = lines[0].split(label, 1)
                lines[0] = feedback.rstrip()
                final_answer = label + answer
                break
    result = []
    solution = False
    step = 0
    for line in lines:
        if line.startswith("Разбор"):
            solution = True
            step = 0
        elif line.startswith(("Ответ:", "Правильный ответ:", "Правильный вариант:")):
            solution = False
        elif solution and line.strip():
            step += 1
            already_numbered = len(line) > 1 and line[0].isdigit() and line[1] in ".)"
            spans = math_spans(line.strip().removesuffix("."))
            formula_line = len(spans) == 1 and spans[0].latex is not None
            if not already_numbered and not formula_line:
                line = f"{step}. {line}"
        result.append(line)
    if final_answer is not None:
        result.extend(("", final_answer))
    return "\n".join(result)
