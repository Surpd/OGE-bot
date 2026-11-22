"""Shared presentation of the saved question, separate from scoring and controls."""

from __future__ import annotations

import base64
from collections.abc import Mapping

from app.math.probability import GRAPH_FAMILIES
from app.math.probability_diagram import render_snapshot as render_probability_diagram


def task13_choice_text(snapshot: Mapping[str, object]) -> str:
    choices = snapshot.get("option_texts")
    if task13_is_graph_choice(snapshot) or not isinstance(choices, list):
        return ""
    return "\n".join(f"{n}. {choice}" for n, choice in enumerate(choices, 1))


def task13_is_graph_choice(snapshot: Mapping[str, object]) -> bool:
    return snapshot.get("family_id") not in ("OGE13-L01", "OGE13-Q01", "OGE13-Q02", "OGE13-Q03")


def question_text(number: int, snapshot: Mapping[str, object]) -> str:
    condition = str(snapshot.get("condition", ""))
    if number == 7:
        choices = snapshot.get("options")
        if not isinstance(choices, list) or len(choices) != 4:
            raise ValueError("The original №7 options are unavailable")
        condition += "\n\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(choices, 1))
    elif number == 13:
        option_text = task13_choice_text(snapshot)
        if option_text:
            condition += "\n\n" + option_text
    return condition


def answer_instruction(number: int, snapshot: Mapping[str, object]) -> str:
    if number in {7, 13}:
        return "Введите номер варианта 1–4."
    if number == 11:
        return "Введите три цифры в порядке А, Б, В. Используйте 1, 2 и 3 по одному разу."
    if number == 19:
        if snapshot.get("answer_policy_id") == "oge19.answer-single-true":
            return "Введите номер верного утверждения: 1, 2 или 3."
        return "Введите номера выбранных утверждений подряд, например 13."
    return "Напишите ответ в чат."


def system_rows(number: int, snapshot: Mapping[str, object]) -> tuple[str, ...] | None:
    family = str(snapshot.get("family_id", ""))
    if number == 13 and family.startswith("OGE13-S"):
        return tuple(str(snapshot["condition"]).splitlines())
    return None


def verified_photo(number: int, snapshot: Mapping[str, object]) -> bytes | None:
    """Read material after the source loader has verified the snapshot and original hash."""
    if number == 10 and snapshot.get("family_id") in GRAPH_FAMILIES:
        return render_probability_diagram(snapshot)
    if number == 13 and task13_is_graph_choice(snapshot):
        from app.math.inequalities import render_option_sheet_snapshot_png

        return render_option_sheet_snapshot_png(snapshot)
    inner = snapshot.get("figure") if number == 16 else snapshot
    if isinstance(inner, Mapping):
        for key in ("graph_png_base64", "png_base64", "image_base64", "picture_base64"):
            payload = inner.get(key)
            if isinstance(payload, str):
                return base64.b64decode(payload, validate=True)
    return None
