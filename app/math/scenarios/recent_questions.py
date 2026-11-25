"""Bounded avoidance of recently issued questions."""

import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import replace
from hashlib import sha256
from random import Random
from typing import cast

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticePlan,
    PracticeRequest,
    QuestionDraft,
    QuestionSnapshot,
    ScenarioCandidateExcluded,
    ScenarioDraft,
    ScenarioSnapshot,
    build_practice_plan,
)

QuestionSignature = tuple[str, str, str]


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _record(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value)


def _fields(record: Mapping[str, object], *keys: str) -> tuple[object, ...]:
    return tuple(record[key] for key in keys)


def _paper_inputs(
    context: Mapping[str, object], model: Mapping[str, object], family: str,
) -> object:
    rows = cast(tuple[tuple[str, int, int], ...], context["rows"])
    if family == "PAPER-F01":
        return context["target_order"], [row[1:] for row in rows]
    if family == "PAPER-F02":
        gap = cast(int, model["target_index"]) - cast(int, model["source_index"])
        return model.get("source_count", 1), gap
    if family == "PAPER-F03":
        return model["value_mm"], model["multiple"]
    if family in {"PAPER-F04", "PAPER-F06"}:
        return (
            model["short_mm"], model["long_mm"], model.get("decimal_places", 1),
            model.get("denominator_side", "long" if family == "PAPER-F04" else "short"),
        )
    if family == "PAPER-F07":
        return _fields(model, "old_pt", "source_long_mm", "target_long_mm")
    raise ValueError("Unaudited PAPER family")


def _stove_inputs(
    context: Mapping[str, object], model: Mapping[str, object], family: str,
) -> object:
    catalogue = cast(tuple[Mapping[str, object], ...], context["stoves"])
    by_id = {row["id"]: row for row in catalogue}
    if family in {"STOVE-F01-CAPACITY-LIMITS", "STOVE-F02-ATTRIBUTE-MATCH"}:
        key = str(model.get("boundary", model.get("attribute")))
        return key, model["displayed_values"], sorted((row["id"], row[key]) for row in catalogue)
    if family == "STOVE-F12-ARCH-RADIUS":
        return _fields(context, "arc_width_cm", "arc_height_cm")

    room = _record(context["room"])
    floor = tuple(sorted(cast(tuple[int, ...], _fields(room, "length_tenths", "width_tenths"))))
    room_dimensions = (*floor, cast(int, room["height_tenths"]))
    if family == "STOVE-F03-VOLUME":
        return sorted(room_dimensions)
    if family == "STOVE-F04-FLOOR-AREA":
        return floor
    if family == "STOVE-F05-WALL-AREA-NET":
        return room_dimensions, _fields(context, "door_width_cm", "door_height_cm")
    if family == "STOVE-F06-PURCHASE-EXTRA-COSTS":
        return by_id[3]["price_rub"], _fields(context, "installation_rub", "delivery_rub")
    if family in {"STOVE-F07-FIT-WOOD-DELIVERY", "STOVE-F08-COST-COMPARISON"}:
        wood = [row for row in catalogue if row["kind"] == "дровяная"]
        boundaries = sorted(_fields(row, "min_m3", "max_m3") for row in wood)
        length, width, height = room_dimensions
        room_volume_thousandths = length * width * height
        volume_dimensions = sorted(room_dimensions)
        selected = next(
            row for row in wood
            if 1000 * cast(int, row["min_m3"])
            <= room_volume_thousandths <= 1000 * cast(int, row["max_m3"])
        )
        if family == "STOVE-F07-FIT-WOOD-DELIVERY":
            return volume_dimensions, boundaries, selected["price_rub"], context["delivery_rub"]
        return (
            volume_dimensions, boundaries, selected["price_rub"],
            by_id[model["electric_stove_id"]]["price_rub"],
            model["comparison"],
            context["installation_rub"] if model["installation_included"] else None,
        )
    if family == "STOVE-F09-DIRECT-DISCOUNT":
        row = next(
            row for row in catalogue
            if row["kind"] == "дровяная" and row["mass_kg"] == model["mass_kg"]
        )
        return model["mass_kg"], row["price_rub"], model["discount_percent"]
    if family == "STOVE-F10-REVERSE-DISCOUNT":
        return by_id[model["stove_id"]]["price_rub"], model["discount_percent"]
    if family == "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS":
        return (
            by_id[model["stove_id"]]["price_rub"],
            _fields(model, "threshold_rub", "item_discount_percent", "delivery_discount_percent"),
            context["delivery_rub"],
        )
    raise ValueError("Unaudited STOVE family")


def _tyres_inputs(
    context: Mapping[str, object], model: Mapping[str, object], family: str,
) -> object:
    if family == "TYRES-TABLE-EXTREME":
        rims = cast(tuple[int, ...], context["table_rims"])
        index = rims.index(cast(int, model["rim"]))
        rows = cast(tuple[Mapping[str, object], ...], context["table"])
        return model["rim"], model["extreme"], sorted(
            cast(int, row["width_mm"]) for row in rows
            if cast(tuple[tuple[int, ...], ...], row["aspect_ratios_by_rim"])[index]
        )
    if family == "TYRES-SIDEWALL":
        return cast(tuple[int, ...], context["sidewall"])[:2]
    if family == "TYRES-DIAMETER":
        return context["base"]
    if family == "TYRES-RADIUS-DELTA":
        first, second = cast(tuple[tuple[int, ...], tuple[int, ...]], context["comparison"])
        # Generated pairs share a disc diameter, which cancels from the subtraction.
        rims = (first[2], second[2]) if first[2] != second[2] else ()
        return first[:2], second[:2], rims, model["direction"]
    if family == "TYRES-PERCENT-ROTATION":
        return _fields(context, "base", "replacement") + (model["rounding"],)
    raise ValueError("Unaudited TYRES family")


def _tariff_inputs(
    context: Mapping[str, object], model: Mapping[str, object], family: str,
) -> object:
    tariff = _record(context["tariff"])
    minutes = cast(tuple[int, ...], context["minutes"])
    if family == "TARIFF-F01-MONTHS-MINUTES":
        targets = cast(tuple[int, ...], model["targets_minutes"])
        return tuple((target, tuple(i for i, value in enumerate(minutes) if value == target))
                     for target in targets)
    if family == "TARIFF-F04-MONTHLY-BILL":
        month = cast(int, model["month_index"])
        data = cast(tuple[int, ...], context["gb_quarters"])
        return minutes[month], data[month], _fields(
            tariff, "monthly_fee_cents", "included_minutes", "included_gb_quarters",
            "extra_minute_cents", "data_pack_quarters", "data_pack_price_cents",
        )
    if family == "TARIFF-F05-EXTREMUM":
        return sorted(minutes)
    if family == "TARIFF-F09-PERCENT-FEE":
        return _fields(tariff, "monthly_fee_cents", "fee_after_increase_cents")
    if family == "TARIFF-F12-HOME-ISP":
        isp = _record(context["isp"])
        plans = cast(tuple[Mapping[str, object], ...], isp["plans"])
        return isp["usage_mb"], sorted(
            _fields(plan, "monthly_fee_cents", "included_mb", "per_mb_cents") for plan in plans
        )
    raise ValueError("Unaudited TARIFF family")


def _garden_inputs(
    context: Mapping[str, object], _model: Mapping[str, object], family: str,
) -> object:
    if family == "GARDEN-01-IDENTIFY":
        return _fields(_record(context["labels"]), "house", "bath", "garage", "greenhouse")
    if family == "GARDEN-02-TILES-PACKS":
        return _fields(context, "grid_side_m", "path_tiles", "pad_tiles", "tiles_per_pack")
    if family == "GARDEN-04-PERIMETER-POLYGON":
        return _fields(context, "grid_side_m", "exposed_perimeter_edges")
    if family == "GARDEN-07-PERCENT-BUILDINGS":
        return _fields(context, "building_areas_m2", "plot_area_m2")
    if family == "GARDEN-09-HEAT-BREAKEVEN":
        heat = _record(context["heat"])
        if "gas_heater_cost" in heat:
            return _fields(
                heat, "gas_heater_cost", "gas_installation_cost", "electric_heater_cost",
                "electric_installation_cost", "gas_m3_per_hour_tenths", "gas_price_per_m3_tenths",
                "electric_kw_tenths", "electric_price_per_kwh_tenths",
            )
        return _fields(
            heat, "gas_upfront", "electric_upfront", "gas_hourly_cents", "electric_hourly_cents",
        )
    raise ValueError("Unaudited GARDEN family")


def _flat_inputs(
    context: Mapping[str, object], model: Mapping[str, object], family: str,
) -> object:
    if family == "FLAT-01-ROOM-MATCH":
        roles = cast(tuple[str, ...], model["rooms_in_order"])
        return _fields(_record(context["room_labels"]), *roles)
    if family == "FLAT-02-TILE-PACK":
        return context["grid_cell_m"], _fields(model, "room_cells", "tile_cells", "pack")
    if family == "FLAT-02-PARQUET-PACK":
        return context["grid_cell_m"], _fields(
            model, "width_cells", "height_cells", "board_m", "pack",
        )
    if family == "FLAT-03-RECT-AREA":
        return context["grid_cell_m"], model["area_cells"]
    if family == "FLAT-04-RECT-PERCENT":
        return _fields(model, "base_cells", "delta_cells")
    if family == "FLAT-05-WASHER-MIN":
        rows = cast(tuple[Mapping[str, object], ...], context["washers"])
        costs = [
            _fields(row, "price", "install", "delivery_pct")
            for row in rows if row["type"] == "вертикальная" and cast(int, row["capacity"]) >= 6
        ]
        return sorted(costs)
    if family == "FLAT-05-INTERNET-MIN":
        internet = _record(context["internet"])
        plans = cast(tuple[Mapping[str, object], ...], internet["plans"])
        return internet["traffic_mb"], sorted(
            (
                (
                    plan["fee"], plan["included_mb"],
                    plan["overage"] if plan["included_mb"] is not None else None,
                )
                for plan in plans
            ),
            key=str,
        )
    raise ValueError("Unaudited FLAT family")


_INPUTS_BY_STORY = {
    "FLAT": _flat_inputs,
    "GARDEN": _garden_inputs,
    "PAPER": _paper_inputs,
    "STOVE": _stove_inputs,
    "TARIFF": _tariff_inputs,
    "TYRES": _tyres_inputs,
}


def question_signature(
    snapshot: ScenarioDraft | ScenarioSnapshot, question: QuestionDraft | QuestionSnapshot,
) -> QuestionSignature:
    """Key by mathematically relevant visible inputs across all presentation modes."""
    identify = _INPUTS_BY_STORY.get(snapshot.story_code)
    if identify is None:
        # ROUTE is not public. Preserve its historical internal signature.
        return question.family_id, " ".join(question.condition.split()), "[]"
    inputs = identify(snapshot.context, question.math_model, question.family_id)
    operands = json.dumps(_plain(inputs), ensure_ascii=False, sort_keys=True)
    return question.family_id, "math-v2", operands


# One seed per reachable input in the certified finite generator domains.
# The acceptance tests verify these witnesses with the same independent oracle
# that gates issuance. Seed values are a way to reach inputs, never their identity.
_FINITE_FAMILY_SEEDS: Mapping[str, tuple[int, ...]] = {
    "FLAT-03-RECT-AREA": (0, 1, 2, 3, 7, 9, 10, 12, 14, 16, 17, 21, 22, 24, 34, 65),
    "FLAT-04-RECT-PERCENT": (
        0, 2, 3, 4, 5, 6, 8, 11, 14, 15, 16, 19, 20, 23, 24, 30, 32, 33, 34, 37, 44, 74, 76,
    ),
    "PAPER-F02": (
        0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 17, 18, 19, 21, 22, 27, 28, 29,
        43, 54, 58, 76, 79, 87, 120, 139,
    ),
    "PAPER-F03": (0, 1, 2, 3, 4, 5, 8, 11, 14, 17, 21, 28, 38),
    "PAPER-F04": (0, 1, 2, 3, 4, 5, 6, 10, 12, 17, 18, 20, 21, 23, 57, 64),
    "PAPER-F06": (0, 2, 3, 5, 6, 8, 9, 10, 11, 12, 14, 16, 20, 41, 57, 67),
    "PAPER-F07": (
        0, 1, 2, 3, 4, 5, 6, 8, 9, 12, 14, 15, 16, 17, 19, 20, 21, 23, 24, 25, 27, 28,
        35, 43, 44, 46, 47, 61, 63, 75, 82, 88, 110, 132,
    ),
    "TARIFF-F09-PERCENT-FEE": (
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19, 22, 23, 24,
        26, 30, 32, 33, 34, 35, 36, 38, 40, 46, 47, 48, 50, 51, 53, 54, 55, 56, 57,
        60, 62, 71, 75, 77, 81, 89, 90, 95, 97, 105, 111, 117, 118, 130, 135, 139,
        164, 170, 182, 258, 278,
    ),
    "GARDEN-04-PERIMETER-POLYGON": (26, 10, 0, 6, 16, 2, 3, 11, 5, 21, 1),
    "TYRES-SIDEWALL": (
        0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 14, 16, 17,
        21, 22, 25, 26, 28, 29, 32, 33, 36, 42, 47, 49, 54, 58, 76,
    ),
    "TYRES-TABLE-EXTREME": (
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 18, 20, 21, 22, 24,
        25, 26, 28, 31, 32, 34, 35, 36, 37, 41, 42, 44, 46, 51, 52, 54, 59, 61, 62,
        67, 72, 76, 77, 80, 84, 94, 100, 101, 106, 112, 113, 114, 123, 128, 135, 136,
        149, 161, 163, 168, 170, 187, 192, 197, 200, 233, 241, 249, 268, 288, 314, 363,
        364, 431, 648, 741, 1004, 1563, 1580,
    ),
    "STOVE-F04-FLOOR-AREA": (
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 22, 23,
        24, 26, 27, 28, 29, 30, 31, 33, 34, 36, 37, 38, 40, 42, 44, 45, 46, 49, 50, 53,
        54, 55, 56, 57, 59, 61, 63, 67, 71, 73, 74, 75, 80, 81, 83, 88, 89, 96, 98, 101,
        109, 113, 114, 117, 120, 122, 124, 125, 127, 129, 132, 135, 136, 138, 139, 140, 141,
        142, 148, 151, 153, 154, 155, 157, 160, 162, 166, 167, 170, 172, 181, 185, 191,
        195, 197, 198, 203, 204, 207, 209, 213, 215, 226, 228, 244, 247, 249, 259, 262, 266,
        277, 282, 283, 285, 286, 305, 312, 323, 327, 371, 373, 376, 391, 466, 474, 487,
        516, 518, 543, 574, 686, 748, 785, 805, 864, 871, 1241, 1358, 1362, 1554, 1637, 1731,
    ),
    "STOVE-F12-ARCH-RADIUS": tuple(range(68)),
}


class NoFreshScenarioVariant(RuntimeError):
    """Every known mathematically distinct variant in a certified pool was issued."""


class ScenarioVariantSearchFailed(RuntimeError):
    """The search failed to produce a fresh variant without proving exhaustion."""


class ScenarioVariantIdentityError(RuntimeError):
    """The generated scenario lacks a valid canonical mathematical signature."""


def signature_fingerprint(signature: QuestionSignature) -> str:
    return sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()


def fresh_family_plan(
    request: PracticeRequest,
    registry: FamilyRegistry,
    recent: Collection[QuestionSignature] = (),
    *,
    recent_fingerprints: Collection[str] = (),
) -> PracticePlan:
    """Find a fresh exact family plan or distinguish exhaustion from a bounded miss."""
    family = request.family_id
    if family is None or request.position is None:
        raise ValueError("Fresh family search requires an exact family and position")
    witnesses = _FINITE_FAMILY_SEEDS.get(family)
    recent_hashes = frozenset(recent_fingerprints)
    rng = Random(request.seed)
    seeds = [request.seed]
    if recent or recent_hashes:
        if witnesses is None:
            seeds.extend(rng.getrandbits(63) for _ in range(4))
            if family.startswith(("FLAT-", "GARDEN-", "PAPER-", "TARIFF-")):
                # Deterministic reserve for small, non-uniform geometry domains.
                # A miss in this sample cannot certify exhaustion.
                seeds.extend(range(64))
        else:
            ordered = list(witnesses)
            rng.shuffle(ordered)
            seeds.extend(seed for seed in ordered if seed != request.seed)
    def accept(scenario: ScenarioDraft, question: QuestionDraft) -> bool:
        try:
            signature = question_signature(scenario, question)
        except (KeyError, IndexError, TypeError, ValueError, StopIteration) as error:
            raise ScenarioVariantIdentityError(family) from error
        return signature not in recent and signature_fingerprint(signature) not in recent_hashes

    for seed in dict.fromkeys(seeds):
        try:
            return build_practice_plan(
                replace(request, seed=seed), registry, accept_exact_candidate=accept,
            )
        except ScenarioCandidateExcluded:
            continue
    if witnesses is not None:
        raise NoFreshScenarioVariant(family)
    raise ScenarioVariantSearchFailed(family)


def is_recent_single(plan: PracticePlan, recent: frozenset[QuestionSignature]) -> bool:
    if plan.mode is not PracticeMode.SINGLE:
        return False
    question = plan.snapshot.questions[plan.selected_positions[0] - 1]
    return question_signature(plan.snapshot, question) in recent


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


def rotated_plan(
    request: PracticeRequest, registry: FamilyRegistry, history: list[str],
    recent: frozenset[QuestionSignature] = frozenset(),
) -> PracticePlan:
    """Keep one world for all five positions. Only retry if a real alternative exists."""
    rng = Random(request.seed)
    stories = registry.available_stories(request.mode, request.position)
    if request.story_code is None and stories and history:
        seen = [family.partition("-")[0] for family in history]
        age = {story: seen.index(story) if story in seen else len(seen) for story in stories}
        oldest = max(age.values())
        request = replace(request, story_code=rng.choice([s for s in stories if age[s] == oldest]))
    best = build_practice_plan(request, registry)
    if not recent and not history:
        return best
    registrations = registry.adapter(best.snapshot.story_code).family_registry

    def score(plan: PracticePlan) -> tuple[int, int]:
        repeated = 0
        for pos in plan.selected_positions:
            families = {f.family_id for f in registrations if f.available and f.position == pos}
            last = next((family for family in history if family in families), None)
            if len(families) > 1 and plan.snapshot.questions[pos - 1].family_id == last:
                repeated += 1
        return _repeat_count(plan, recent), repeated

    best_score = score(best)
    for _ in range(4):
        if best_score == (0, 0):
            break
        trial = build_practice_plan(replace(request, seed=rng.getrandbits(63)), registry)
        trial_score = score(trial)
        if trial_score < best_score:
            best, best_score = trial, trial_score
    return best
