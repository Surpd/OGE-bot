"""Bounded avoidance of recently issued questions."""

import json
import re
from collections.abc import Callable, Mapping
from typing import cast

from app.math.scenario_engine import PracticeMode, PracticePlan, QuestionSnapshot, ScenarioSnapshot

QuestionSignature = tuple[str, str, str]


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _visible_inputs(snapshot: ScenarioSnapshot, question: QuestionSnapshot) -> object:
    context, model = snapshot.context, question.math_model
    family = question.family_id
    if family == "TYRES-TABLE-EXTREME":
        rims = cast(tuple[int, ...], context["table_rims"])
        index = rims.index(cast(int, model["rim"]))
        rows = cast(tuple[Mapping[str, object], ...], context["table"])
        return [
            (
                row["width_mm"],
                bool(cast(tuple[tuple[int, ...], ...], row["aspect_ratios_by_rim"])[index]),
            )
            for row in rows
        ]
    if family in {"TYRES-DIAMETER", "TYRES-PERCENT-ROTATION"}:
        return context["base_marking"]
    if family == "PAPER-F01":
        return [row[1:] for row in cast(tuple[tuple[object, ...], ...], context["rows"])]
    if family in {"STOVE-F01-CAPACITY-LIMITS", "STOVE-F02-ATTRIBUTE-MATCH"}:
        from app.math.scenarios.stories.STOVE import _rows

        key = str(model.get("boundary", model.get("attribute")))
        return [(row["id"], row[key]) for row in _rows(context)]
    if family.startswith("STOVE-F") and family[7:9] in {"08", "09", "10", "11", "12"}:
        from app.math.scenarios.stories.STOVE import _rows

        catalogue = _rows(context)
        if family.startswith("STOVE-F08"):
            return (
                context["room"],
                [
                    tuple(row[key] for key in ("id", "kind", "min_m3", "max_m3"))
                    for row in catalogue
                ],
                [
                    (row["id"], row["price_rub"])
                    for row in catalogue
                    if row["id"] in (model.get("wood_stove_id"), model.get("electric_stove_id"))
                ],
                context["installation_rub"] if model.get("installation_included") else None,
            )
        if family.startswith("STOVE-F09"):
            mass = re.search(r"массой (\d+) кг", question.condition)
            return [
                (row["mass_kg"], row["price_rub"])
                for row in catalogue
                if mass and row["mass_kg"] == int(mass[1])
            ]
        if family.startswith("STOVE-F10"):
            selected = re.search(r"№(\d+)", question.condition)
            return [
                (row["id"], row["price_rub"])
                for row in catalogue
                if selected and row["id"] == int(selected[1])
            ]
        if family.startswith("STOVE-F11"):
            return [(row["id"], row["price_rub"]) for row in catalogue if row["id"] == 2]
        return context["arc_width_cm"], context["arc_height_cm"]
    if family == "GARDEN-09-HEAT-BREAKEVEN":
        heat = cast(Mapping[str, object], context["heat"])
        return {key: value for key, value in heat.items() if key != "break_even_hours"}
    if family in {"PAPER-F03", "PAPER-F04", "PAPER-F06", "PAPER-F07"}:
        relevant = "A0" if family == "PAPER-F03" else "A3"
        return [
            row[1:]
            for row in cast(tuple[tuple[object, ...], ...], context["rows"])
            if row[0] == relevant
        ]
    if family in {"TARIFF-F01-MONTHS-MINUTES", "TARIFF-F05-EXTREMUM"}:
        return context["minutes"]
    if family == "TARIFF-F04-MONTHLY-BILL":
        month = cast(int, model["month_index"])
        minutes = cast(tuple[int, ...], context["minutes"])
        data = cast(tuple[int, ...], context["gb_quarters"])
        tariff = cast(Mapping[str, object], context["tariff"])
        keys = (
            "monthly_fee_cents",
            "included_minutes",
            "included_gb_quarters",
            "extra_minute_cents",
            "data_pack_quarters",
            "data_pack_price_cents",
        )
        return minutes[month], data[month], tuple(tariff[key] for key in keys)
    if family == "TARIFF-F12-HOME-ISP":
        return cast(Mapping[str, object], context["isp"])["plans"]
    if family in {"GARDEN-01-IDENTIFY", "FLAT-01-ROOM-MATCH"}:
        key = "labels" if snapshot.story_code == "GARDEN" else "room_labels"
        labels = cast(Mapping[str, int], context[key])
        roles = (
            ("house", "bath", "garage", "greenhouse")
            if key == "labels"
            else cast(tuple[str, ...], model["rooms_in_order"])
        )
        return tuple(labels[role] for role in roles)
    # The other questions state the variable operands in their condition, or use
    # geometry fixed within the family. Do not hash the rest of the shared world.
    return ()


def question_signature(snapshot: ScenarioSnapshot, question: QuestionSnapshot) -> QuestionSignature:
    """Key by the task and its visible operands, independent of answer and PNG bytes."""
    inputs = json.dumps(
        _plain(_visible_inputs(snapshot, question)), ensure_ascii=False, sort_keys=True
    )
    return question.family_id, " ".join(question.condition.split()), inputs


_FIXED_SINGLE_FAMILIES = frozenset(
    {
        "GARDEN-04-PERIMETER-POLYGON",
        "GARDEN-07-PERCENT-BUILDINGS",
        "FLAT-03-RECT-AREA",
        "FLAT-04-RECT-PERCENT",
        "FLAT-05-WASHER-MIN",
        "PAPER-F03",
        "PAPER-F04",
        "PAPER-F06",
    }
)


def is_recent_fixed_single(plan: PracticePlan, recent: frozenset[QuestionSignature]) -> bool:
    if plan.mode is not PracticeMode.SINGLE:
        return False
    question = plan.snapshot.questions[plan.selected_positions[0] - 1]
    return (
        question.family_id in _FIXED_SINGLE_FAMILIES
        and question_signature(plan.snapshot, question) in recent
    )


def prefer_unseen(
    generate: Callable[[], PracticePlan],
    recent: frozenset[tuple[str, str, str]],
    *,
    attempts: int = 5,
) -> PracticePlan:
    best = generate()
    best_count = _repeat_count(best, recent)
    for _ in range(attempts - 1):
        if not best_count:
            break
        candidate = generate()
        count = _repeat_count(candidate, recent)
        if count < best_count:
            best, best_count = candidate, count
    return best


def _repeat_count(plan: PracticePlan, recent: frozenset[tuple[str, str, str]]) -> int:
    return sum(
        question_signature(plan.snapshot, plan.snapshot.questions[position - 1]) in recent
        for position in plan.selected_positions
    )
