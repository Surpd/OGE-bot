"""Exact inputs to existing generators and immutable regression snapshots."""

import json
from functools import cache
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any

from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.persistence.error_replay import _scenario_question
from app.persistence.part2_bank import ATLAS, load_bank
from app.persistence.rotation_history import enabled

MODULES = {
    6: "generator",
    7: "numbers",
    8: "oge8",
    9: "equations",
    10: "probability",
    11: "oge11",
    12: "formulas",
    13: "inequalities",
    14: "progressions",
    15: "oge15_triangles",
    16: "oge16_circles",
    17: "oge17_generator",
    18: "oge18",
}


def identity(card: dict[str, Any]) -> str:
    return sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


@cache
def bank_cards() -> tuple[dict[str, Any], ...]:
    approved = json.loads((ATLAS / "reviewed_versions.json").read_text())
    return tuple(
        json.loads(payload)
        for tid, _, payload, digest in load_bank()[1]
        if approved.get(tid) == digest
    )


def generate(number: int, family: str, seed: int = 0, version: str | None = None) -> dict[str, Any]:
    if not 0 <= seed < 2**63:
        raise ValueError("Seed out of range")
    scenario = None
    if number <= 5:
        registry = public_registry()
        story = family.removeprefix("OGE15:")
        exact_family = None
        if story not in registry.story_codes:
            exact_family = family
            story = next(
                (
                    code
                    for code in registry.available_stories(PracticeMode.SINGLE, number)
                    if any(
                        item.family_id == family and item.position == number and item.available
                        for item in registry.adapter(code).family_registry
                    )
                ),
                "",
            )
            if not story:
                raise ValueError("Exact story family unavailable")
        scenario = build_practice_plan(
            PracticeRequest(PracticeMode.SINGLE, seed, story, number, exact_family), registry
        ).snapshot.to_snapshot()
        if version is not None and scenario["generator_version"] != version:
            raise ValueError("Historical story generator unavailable; use a saved snapshot")
        snapshot = _scenario_question(scenario, number)
    elif number == 19:
        # The scheduler records phase/history-dependent inputs. A seed alone cannot
        # promise reconstruction of an arbitrary previously issued triple.
        if version is not None:
            raise ValueError("№19 requires the saved snapshot, not seed alone")
        from app.math.oge19_scheduler import build_task19_candidate_batch

        if family not in enabled(number):
            raise ValueError("Family unavailable")
        rows = build_task19_candidate_batch(
            {"family_queue": [family]}, seed, enabled_families=(family,)
        )
        if not rows:
            raise ValueError("Exact family unavailable")
        snapshot = rows[0]
    else:
        if family not in enabled(number):
            raise ValueError("Family unavailable")
        module_name = (
            "oge07_graph" if number == 7 and family.startswith("OGE07-N") else MODULES[number]
        )
        module = import_module("app.math." + module_name)
        name = (
            "generate_equation"
            if number == 9
            else ("generate_graph_problem" if module_name == "oge07_graph" else "generate")
        )
        if version is None and number == 15:
            from app.math.oge15_complete import VERSION

            version = VERSION
        if version is None and number == 18 and family in module.NEW_FAMILIES:
            version = module.GENERATOR_VERSION_V2
        args = (family, seed) if version is None else (family, seed, version)
        snapshot = getattr(module, name)(*args).to_snapshot()
    return {
        "number": number,
        "snapshot": snapshot,
        "scenario": scenario,
        "note": "Сохранён точный снимок. Это проверка показа, не сертификация математики.",
    }


def fixture(index: int) -> dict[str, Any]:
    manifest = json.loads((Path(__file__).parent / "fixtures.json").read_text())
    entry = manifest[index]
    if identity(entry["card"]) != entry["digest"]:
        raise ValueError("Regression fixture digest mismatch")
    return dict(entry["card"])


STARTERS = (
    "Печи · 23 / 12 / 20",
    "№16 · прямой угол · известный дефект",
    "Формулы · Rich / PNG",
    "№20 · фото без модели",
)
