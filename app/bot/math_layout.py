"""Presentation of owned training headings; never changes formula tokens."""

from app.bot.math_notation import math_spans


def action_prefix(line: str) -> str | None:
    action, separator, _ = line.partition(":")
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
            if not already_numbered:
                line = f"{step}. {line}"
        result.append(line)
    if final_answer is not None:
        result.extend(("", final_answer))
    return "\n".join(result)
