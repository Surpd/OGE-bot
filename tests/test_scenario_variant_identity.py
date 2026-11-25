"""Math identity regression for every public OGE 1–5 family."""
import json
from dataclasses import replace
from itertools import product

import pytest

from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.math.scenario_engine import (
    FamilyQuestionBuilder,
    FamilyScenarioGenerator,
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    build_practice_plan,
)
from app.math.scenarios import recent_questions as identity
from app.math.scenarios.stories.STOVE import _PYTHAGOREAN_PAIRS
from app.math.scenarios.stories.TYRES import _ASPECTS, _RIMS, _WIDTHS

PUBLIC = sorted(
    (code, family) for code, families in PUBLIC_FAMILIES.items() for family in families
)
CAPACITIES = {
    **dict.fromkeys(identity._FIXED_SINGLE_FAMILIES, 1),
    "FLAT-02-TILE-PACK": 5,
    "FLAT-02-PARQUET-PACK": 4,
    "FLAT-05-INTERNET-MIN": 6,
    "GARDEN-02-TILES-PACKS": 8,
    "PAPER-F02": 6,
    "PAPER-F07": 2,
    "STOVE-F04-FLOOR-AREA": len({
        tuple(sorted((length, width)))
        for length, width, height in product(range(24, 39), range(19, 30), range(19, 28))
        if 13000 <= length * width * height <= 20000
    }),
    "STOVE-F12-ARCH-RADIUS": len(_PYTHAGOREAN_PAIRS),
    "TARIFF-F09-PERCENT-FEE": 4,
    "TYRES-SIDEWALL": len(_WIDTHS) * len(_ASPECTS),
    # The first and last occupied widths span at least three steps. Two spans
    # of three steps have two optional interior widths; one span of four has three.
    "TYRES-TABLE-EXTREME": len(_RIMS[1:-1]) * (2 * 2**2 + 2**3),
}

UNRELATED_BY_STORY = {
    "FLAT": ("internet", "traffic_mb"),
    "GARDEN": ("greenhouse_area_m2",),
    "PAPER": ("questions", "5", "old_pt"),
    "STOVE": ("arc_width_cm",),
    "TARIFF": ("tariff", "annual_sms"),
    "TYRES": ("sidewall", 2),
}
UNRELATED_EXCEPTIONS = {
    "FLAT-05-INTERNET-MIN": ("washers", 0, "height"),
    "PAPER-F07": ("rows", "A0", 2),
    "STOVE-F12-ARCH-RADIUS": ("stoves", 0, "price_rub"),
}

OPERAND_PATHS = {
    "FLAT-01-ROOM-MATCH": ("room_labels", "bathroom"),
    "FLAT-02-TILE-PACK": ("model", "pack"),
    "FLAT-02-PARQUET-PACK": ("model", "pack"),
    "FLAT-03-RECT-AREA": ("model", "area_cells"),
    "FLAT-04-RECT-PERCENT": ("model", "base_cells"),
    "FLAT-05-WASHER-MIN": ("washers", 2, "price"),
    "FLAT-05-INTERNET-MIN": ("internet", "traffic_mb"),
    "GARDEN-01-IDENTIFY": ("labels", "house"),
    "GARDEN-02-TILES-PACKS": ("tiles_per_pack",),
    "GARDEN-04-PERIMETER-POLYGON": ("exposed_perimeter_edges",),
    "GARDEN-07-PERCENT-BUILDINGS": ("plot_area_m2",),
    "GARDEN-09-HEAT-BREAKEVEN": ("heat", "gas_installation_cost"),
    "PAPER-F01": ("rows", 0, 1),
    "PAPER-F02": ("model", "target_index"),
    "PAPER-F03": ("rows", "A0", 2),
    "PAPER-F04": ("rows", "A3", 1),
    "PAPER-F06": ("rows", "A3", 2),
    "PAPER-F07": ("model", "old_pt"),
    "STOVE-F01-CAPACITY-LIMITS": ("model", "displayed_values", 0),
    "STOVE-F02-ATTRIBUTE-MATCH": ("model", "displayed_values", 0),
    "STOVE-F03-VOLUME": ("room", "height_tenths"),
    "STOVE-F04-FLOOR-AREA": ("room", "length_tenths"),
    "STOVE-F05-WALL-AREA-NET": ("door_width_cm",),
    "STOVE-F06-PURCHASE-EXTRA-COSTS": ("stoves", 2, "price_rub"),
    "STOVE-F07-FIT-WOOD-DELIVERY": ("stoves", 1, "price_rub"),
    "STOVE-F08-COST-COMPARISON": ("stoves", 2, "price_rub"),
    "STOVE-F09-DIRECT-DISCOUNT": ("model", "discount_percent"),
    "STOVE-F10-REVERSE-DISCOUNT": ("model", "discount_percent"),
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": ("delivery_rub",),
    "STOVE-F12-ARCH-RADIUS": ("arc_width_cm",),
    "TARIFF-F01-MONTHS-MINUTES": ("model", "targets_minutes", 0),
    "TARIFF-F04-MONTHLY-BILL": ("tariff", "extra_minute_cents"),
    "TARIFF-F05-EXTREMUM": ("minutes", 0),
    "TARIFF-F09-PERCENT-FEE": ("tariff", "fee_after_increase_cents"),
    "TARIFF-F12-HOME-ISP": ("isp", "usage_mb"),
    "TYRES-TABLE-EXTREME": ("table", 0, "width_mm"),
    "TYRES-SIDEWALL": ("sidewall", 0),
    "TYRES-DIAMETER": ("base", 2),
    "TYRES-RADIUS-DELTA": ("comparison", 0, 1),
    "TYRES-PERCENT-ROTATION": ("replacement", 0),
}


def _request(story, family, registry, seed=0):
    registration = next(
        item for item in registry.adapter(story).family_registry if item.family_id == family
    )
    return PracticeRequest(PracticeMode.SINGLE, seed, story, registration.position, family)


def _mathematical_mutation(scene, position, path):
    payload = scene.to_snapshot()
    field, *rest = path
    if field == "model":
        node = payload["questions"][position - 1]["math_model"]
    else:
        node = payload["context"]
        rest.insert(0, field)
    for part in rest[:-1]:
        if isinstance(node, list) and isinstance(part, str):
            node = next(row for row in node if row[0] == part)
        else:
            node = node[part]
    node[rest[-1]] += 1
    return ScenarioSnapshot.from_snapshot(payload)


@pytest.mark.parametrize("story,family", PUBLIC, ids=[family for _, family in PUBLIC])
def test_public_mathematical_inputs_and_five_issue_cycle(story, family):
    registry = public_registry()
    request = _request(story, family, registry)
    position = request.position
    seen = set()
    for index in range(min(CAPACITIES.get(family, 5), 5)):
        # Each subsequent issue starts on a known repeat.
        plan = identity.fresh_family_plan(request, registry, recent_fingerprints=seen)
        scene = plan.snapshot
        question = scene.questions[position - 1]
        assert plan.selected_positions == (position,)
        assert question.family_id == family
        signature = identity.question_signature(scene, question)
        fingerprint = identity.signature_fingerprint(signature)
        assert fingerprint not in seen
        seen.add(fingerprint)
        request = replace(request, seed=scene.seed)
        if index == 0:
            cosmetic = replace(
                scene,
                shared_context="Другая подача того же сюжета",
                context={**scene.context, "illustration_palette": "red"},
            )
            assert identity.question_signature(
                cosmetic, replace(question, condition="Переформулировано", canonical_answer="999"),
            ) == signature
            unrelated = _mathematical_mutation(
                scene, position, UNRELATED_EXCEPTIONS.get(family, UNRELATED_BY_STORY[story]),
            )
            assert identity.question_signature(unrelated, unrelated.questions[position - 1]) == (
                signature
            )
            full = replace(plan, mode=PracticeMode.FULL, selected_positions=(1, 2, 3, 4, 5))
            assert identity._repeat_count(full, frozenset({signature})) == 1
            restored = ScenarioSnapshot.from_snapshot(json.loads(json.dumps(scene.to_snapshot())))
            assert identity.question_signature(restored, restored.questions[position - 1]) == (
                signature
            )
            mutated = _mathematical_mutation(scene, position, OPERAND_PATHS[family])
            assert identity.question_signature(mutated, mutated.questions[position - 1]) != (
                signature
            )


@pytest.mark.parametrize("family", sorted(CAPACITIES))
def test_certified_pool_exhaustion_uses_distinct_math_witnesses(family):
    registry = public_registry()
    story = family.split("-")[0]
    request = _request(story, family, registry)
    adapter = registry.adapter(story)
    seeds = identity._FINITE_FAMILY_SEEDS[family]
    fingerprints = set()
    for seed in seeds:
        generator = adapter.generator
        scenario = (
            generator.generate_scenario_for_family(seed, request.position, family)
            if isinstance(generator, FamilyScenarioGenerator)
            else generator.generate_scenario(seed)
        )
        question = adapter.question_builder.build_question(scenario, request.position)
        if isinstance(adapter.question_builder, FamilyQuestionBuilder):
            question = adapter.question_builder.build_question_for_family(
                scenario, request.position, family,
            )
        assert question.family_id == family
        fingerprints.add(identity.signature_fingerprint(
            identity.question_signature(scenario, question)
        ))
    assert len(seeds) == len(fingerprints) == CAPACITIES[family]
    with pytest.raises(identity.NoFreshScenarioVariant):
        identity.fresh_family_plan(request, registry, recent_fingerprints=fingerprints)


def test_floor_ignores_height_door_catalogue_and_dimension_order():
    registry = public_registry()
    floor = _request("STOVE", "STOVE-F04-FLOOR-AREA", registry)
    selection = build_practice_plan(floor, registry)
    question = selection.snapshot.questions[2]
    scene = selection.snapshot
    before = identity.question_signature(scene, question)
    room = dict(scene.context["room"])
    room["length_tenths"], room["width_tenths"] = room["width_tenths"], room["length_tenths"]
    room["height_tenths"] += 1
    catalogue = [dict(row) for row in scene.context["stoves"]]
    catalogue[0]["price_rub"] += 900
    after = replace(scene, context={
        **scene.context, "room": room, "door_width_cm": 123, "stoves": catalogue,
    })
    assert identity.question_signature(after, question) == before

    world = build_practice_plan(PracticeRequest(PracticeMode.FULL, 0, "STOVE"), registry)
    assert identity.question_signature(world.snapshot, world.snapshot.questions[2]) == before


def test_repeat_search_miss_is_not_certified_exhaustion(monkeypatch):
    registry = public_registry()
    request = _request("STOVE", "STOVE-F03-VOLUME", registry)
    tried = []

    def reject(request, registry, **kwargs):
        tried.append(request.seed)
        raise identity.ScenarioCandidateExcluded

    monkeypatch.setattr(identity, "build_practice_plan", reject)
    with pytest.raises(identity.ScenarioVariantSearchFailed):
        identity.fresh_family_plan(request, registry, recent_fingerprints={"old"})
    assert len(tried) == len(set(tried)) == 5

def test_bad_signature_is_an_identity_error(monkeypatch):
    registry = public_registry()
    request = _request("STOVE", "STOVE-F04-FLOOR-AREA", registry)

    def bad_signature(scene, question):
        raise KeyError("operand")

    monkeypatch.setattr(identity, "question_signature", bad_signature)
    with pytest.raises(identity.ScenarioVariantIdentityError):
        identity.fresh_family_plan(request, registry)
