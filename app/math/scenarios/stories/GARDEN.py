"""Research-bounded garden plot adapter for the OGE 1–5 scenario engine.

The first release deliberately uses the visually checked Sosnovka topology only.
All coordinates are source-independent vector geometry in half-metre units.
"""

# SVG path/data strings are intentionally long single attributes.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from math import ceil
from random import Random
from types import MappingProxyType
from typing import cast
from xml.etree import ElementTree

from app.math.scenario_engine import (
    AnswerPolicy,
    FamilyRegistration,
    FamilyStatus,
    JsonValue,
    QuestionDraft,
    RenderedScenario,
    ScenarioAssetRef,
    ScenarioDraft,
    ScenarioSnapshot,
    StoryAdapter,
)

VERSION = "garden-sosnovka-1.0"
POLICY_VERSION = "1"
SOURCE_IDS = ("408405", "408413", "408424", "408432", "408438")
FAMILIES = tuple(
    f"GARDEN-{n:02d}-{name}"
    for n, name in (
        (1, "IDENTIFY"),
        (2, "TILES-PACKS"),
        (4, "PERIMETER-POLYGON"),
        (7, "PERCENT-BUILDINGS"),
        (9, "HEAT-BREAKEVEN"),
    )
)


def _world(seed: int) -> dict[str, JsonValue]:
    rng = Random(seed ^ 0x6A4D)
    # Bounded source-preserving tariff variants; geometry and non-economic values
    # remain the exact single confirmed Sosnovka fixture.
    hours = 500 if seed == 0 else rng.randrange(5, 26) * 50
    gas_hourly = 784
    electric_hourly = 2058
    premium = (electric_hourly - gas_hourly) * hours // 100
    base = 29_000 if seed == 0 else 2_900_000 + rng.randrange(0, 100) * 100
    return {
        "template_id": "SOSNOVKA-2025-1.1",
        "world_version": VERSION,
        "grid_side_m": 2,
        "plot_area_m2": 600,
        "labels": {
            "house": 7,
            "bath": 4,
            "garage": 2,
            "greenhouse": 5,
            "shed": 1,
            "orchard": 3,
            "garden": 6,
        },
        "building_areas_m2": (68, 48, 24, 36),
        "exposed_perimeter_edges": 18,
        "path_tiles": 25,
        "pad_tiles": 40,
        "tiles_per_pack": 10,
        "garden_area_m2": 120,
        "greenhouse_area_m2": 12,
        "heat": {
            "gas_upfront": base + premium,
            "electric_upfront": base,
            "gas_hourly_cents": gas_hourly,
            "electric_hourly_cents": electric_hourly,
            "break_even_hours": hours,
        },
        "scenario_seed": seed,
    }


def _svg(ctx: Mapping[str, JsonValue]) -> bytes:
    # Fixed 30 m x 20 m plot. One metre is 10 SVG units, matching the
    # 20-unit grid and 10-unit (1 m) paved paths.
    labels = cast(Mapping[str, int], ctx["labels"])
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 400 300">',
        '<rect width="400" height="300" fill="#fff"/>',
        '<g stroke="#d9e3d2" stroke-width=".7">',
    ]
    for x in range(20, 321, 20):
        parts.append(f'<path d="M{x} 20V220"/>')
    for y in range(20, 221, 20):
        parts.append(f'<path d="M20 {y}H320"/>')
    parts.extend(
        [
            "</g>",
            '<path d="M20 20H320V110 M320 130V220H20Z" fill="none" stroke="#283b2d" stroke-width="3"/>',
            '<text x="322" y="124" font-size="8">Ворота</text>',
            '<path data-role="paving" d="M320 120H200V180H110" fill="none" stroke="#b99d6b" stroke-width="10" stroke-linecap="butt" stroke-linejoin="round"/>',
            '<rect data-role="pad" x="210" y="100" width="80" height="50" fill="#d9c99e" stroke="#725f3e"/>',
            '<path data-role="house" d="M120 20H200V80H220V100H120Z" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="bath" x="40" y="130" width="60" height="80" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garage" x="260" y="160" width="40" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="shed" x="240" y="20" width="60" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garden" x="80" y="100" width="120" height="100" fill="#a8d88a" stroke="#39783d"/>',
            '<rect data-role="greenhouse" x="120" y="130" width="30" height="40" fill="#a9dce6" stroke="#267085"/>',
            '<g data-role="orchard" fill="#478e42"><circle cx="50" cy="50" r="7"/><circle cx="75" cy="50" r="7"/><circle cx="50" cy="75" r="7"/></g>',
        ]
    )
    label_points = {
        "house": (170, 50),
        "bath": (70, 170),
        "garage": (280, 190),
        "shed": (270, 50),
        "greenhouse": (135, 152),
        "garden": (170, 180),
        "orchard": (62, 100),
    }
    for role, (x, y) in label_points.items():
        parts.append(
            f'<text data-label="{role}" x="{x}" y="{y}" text-anchor="middle" font-size="9">{labels[role]}</text>'
        )
    parts.extend(
        [
            '<text x="338" y="40" font-size="8">Условные обозначения</text>',
            '<text x="338" y="56" font-size="7">1 — сарай</text><text x="338" y="70" font-size="7">2 — гараж</text>',
            '<text x="338" y="84" font-size="7">3 — яблони</text><text x="338" y="98" font-size="7">4 — баня</text>',
            '<text x="338" y="112" font-size="7">5 — теплица</text><text x="338" y="126" font-size="7">6 — огород</text>',
            '<text x="338" y="140" font-size="7">7 — жилой дом</text>',
            '<path d="M340 180H390" stroke="#333" stroke-width="2"/><path d="M340 176V184M390 176V184" stroke="#333"/>',
            '<text x="340" y="194" font-size="7">Масштаб: 2 м на клетку</text>',
            '<text x="24" y="240" font-size="8">Дорожки и площадка вымощены плиткой 1×1 м; ширина дорожки — 1 м.</text>',
            '<text x="24" y="258" font-size="8">Аналог ОГЭ: схема участка, клетка — 2 м.</text>',
            "</svg>",
        ]
    )
    return "".join(parts).encode("utf-8")


class _Policy:
    policy_id = "integer_or_code"
    version = POLICY_VERSION

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        return raw_answer.strip() == canonical_answer


class _Generator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        ctx = _world(seed)
        return ScenarioDraft(
            "GARDEN",
            seed,
            VERSION,
            ctx,
            "garden-compat-1",
            ("408405", "408413", "408424", "408432", "408438"),
        )


class _Builder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        c = scenario.context
        labels = cast(Mapping[str, int], c["labels"])
        areas = cast(tuple[int, ...], c["building_areas_m2"])
        if position == 1:
            answer = "".join(str(labels[k]) for k in ("house", "bath", "garage", "greenhouse"))
            condition = "На плане дачного участка найдите номера дома, бани, гаража и теплицы. Запишите цифры в указанном порядке."
        elif position == 2:
            answer = str(
                ceil(
                    (cast(int, c["path_tiles"]) + cast(int, c["pad_tiles"]))
                    / cast(int, c["tiles_per_pack"])
                )
            )
            condition = "Для дорожек и площадки использовали плитки одного размера. Всего 25 плиток дорожек и 40 плиток площадки; в пачке 10 плиток. Сколько пачек купили?"
        elif position == 3:
            answer = str(cast(int, c["exposed_perimeter_edges"]) * cast(int, c["grid_side_m"]))
            condition = "Дом имеет ломаную форму по сторонам клеток плана. Найдите периметр его внешнего контура в метрах, если сторона клетки 2 м."
        elif position == 4:
            answer = str(round(sum(areas) / cast(int, c["plot_area_m2"]) * 100))
            condition = "Площадь дома 68 м², бани 48 м², гаража 24 м² и сарая 36 м². Площадь участка 600 м². Найдите, сколько процентов площади участка занимают эти постройки. Ответ округлите до целого."
        elif position == 5:
            heat = cast(Mapping[str, int], c["heat"])
            answer = str(heat["break_even_hours"])
            condition = f"Сравните отопление газом и электричеством по плану и данным: начальные затраты газ — {heat['gas_upfront']} руб., электричество — {heat['electric_upfront']} руб.; расходы за час — {heat['gas_hourly_cents'] / 100:.2f} и {heat['electric_hourly_cents'] / 100:.2f} руб. Через сколько часов суммарные затраты сравняются?"
        else:
            raise ValueError("Garden position must be 1..5")
        return QuestionDraft(
            position,
            scenario.seed,
            FAMILIES[position - 1],
            VERSION,
            condition,
            "integer_or_code",
            POLICY_VERSION,
            answer,
            ("Считайте данные с общего плана и примените нужную операцию.",),
            (f"По модели позиции {position} получаем {answer}.",),
            {"position": position, "expected": answer},
        )


class _Renderer:
    @staticmethod
    def _shared_context(scenario: ScenarioDraft) -> str:
        context = scenario.context
        heat = cast(Mapping[str, int], context["heat"])
        return (
            "План участка: клетка 2 м; дорожки шириной 1 м. Плитка 1×1 м.\n"
            f"Плитка: дорожки — {context['path_tiles']} шт.; площадка — {context['pad_tiles']} шт.; "
            f"в пачке {context['tiles_per_pack']} шт.\n"
            "Отопление | начальные затраты | расходы за час\n"
            f"Газ | {heat['gas_upfront']} руб. | {heat['gas_hourly_cents'] / 100:.2f} руб./ч\n"
            f"Электричество | {heat['electric_upfront']} руб. | "
            f"{heat['electric_hourly_cents'] / 100:.2f} руб./ч\n"
            "Все пять вопросов относятся к одному плану. Аналог ОГЭ."
        )

    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        image = _svg(scenario.context)
        digest = sha256(image).hexdigest()
        ref = ScenarioAssetRef(digest, "image/svg+xml", f"sha256/{digest}.svg")
        return RenderedScenario(self._shared_context(scenario), (ref,))

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if asset.content_type != "image/svg+xml":
            raise ValueError("Unknown garden asset")
        return _svg(snapshot.context)


class _Oracle:
    def validate_svg_bytes(self, scenario: ScenarioDraft, image: bytes) -> None:
        """Reject moved structures, changed labels, scale, or paving width."""
        if image != _svg(scenario.context):
            raise ValueError("SVG bytes do not match the immutable garden geometry")
        ElementTree.fromstring(image)

    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        c = scenario.context
        if c.get("template_id") != "SOSNOVKA-2025-1.1" or c.get("scenario_seed") != scenario.seed:
            raise ValueError("Unverified garden topology or mismatched seed")
        labels = cast(Mapping[str, int], c["labels"])
        if len(set(labels.values())) != len(labels) or set(labels.values()) != set(range(1, 8)):
            raise ValueError("Garden labels must be a unique source-verified mapping")
        heat = cast(Mapping[str, int], c["heat"])
        if int(heat["gas_hourly_cents"]) >= int(heat["electric_hourly_cents"]):
            raise ValueError("Invalid heating rates")
        if (int(heat["gas_upfront"]) - int(heat["electric_upfront"])) * 100 != (
            int(heat["electric_hourly_cents"]) - int(heat["gas_hourly_cents"])
        ) * int(heat["break_even_hours"]):
            raise ValueError("Heating figures do not break even")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        self.validate_scenario(scenario)
        if rendered.shared_context != _Renderer._shared_context(scenario):
            raise ValueError("Shared plan/table text differs from the immutable world")
        if (
            question.scenario_seed != scenario.seed
            or question.family_id != FAMILIES[question.position - 1]
        ):
            raise ValueError("Question family/seed mismatch")
        if question.position == 1:
            labels = cast(Mapping[str, int], scenario.context["labels"])
            expected = "".join(str(labels[k]) for k in ("house", "bath", "garage", "greenhouse"))
            if question.canonical_answer != expected:
                raise ValueError("Rendered object order differs from plan")
            for term in ("дом", "бан", "гараж", "теплиц", "указанном порядке"):
                if term not in question.condition:
                    raise ValueError("Identify wording does not match its answer order")
        elif question.position == 2:
            if question.canonical_answer != str(ceil(65 / 10)):
                raise ValueError("Tile pack answer mismatch")
            if not all(value in question.condition for value in ("25", "40", "10")):
                raise ValueError("Tile values in text differ from plan")
        elif question.position == 3:
            if question.canonical_answer != "36":
                raise ValueError("Perimeter mismatch")
            if "2 м" not in question.condition or "внешнего контура" not in question.condition:
                raise ValueError("Perimeter wording or scale mismatch")
        elif question.position == 4:
            if question.canonical_answer != "29":
                raise ValueError("Building percentage mismatch")
            if not all(
                value in question.condition for value in ("68", "48", "24", "36", "600", "целого")
            ):
                raise ValueError("Building areas or denominator differ from plan")
        elif question.position == 5:
            heat = cast(Mapping[str, int], scenario.context["heat"])
            if question.canonical_answer != str(heat["break_even_hours"]):
                raise ValueError("Heating answer mismatch")
            visible = (
                str(heat["gas_upfront"]),
                str(heat["electric_upfront"]),
                f"{heat['gas_hourly_cents'] / 100:.2f}",
                f"{heat['electric_hourly_cents'] / 100:.2f}",
            )
            if not all(value in question.condition for value in visible):
                raise ValueError("Heating table differs from condition")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(q.position for q in questions) != (1, 2, 3, 4, 5):
            raise ValueError("Garden bundle must be a coherent ordered five")
        for q in questions:
            self.validate_question(scenario, q, rendered)
        image = _svg(scenario.context)
        self.validate_svg_bytes(scenario, image)
        root = ElementTree.fromstring(image)
        if (
            len(root.findall(".//*[@data-role='house']")) != 1
            or len(root.findall(".//*[@data-role='greenhouse']")) != 1
        ):
            raise ValueError("Garden plan is missing a required shape")
        labels = {el.attrib["data-label"]: el.text for el in root.findall(".//*[@data-label]")}
        expected = cast(Mapping[str, int], scenario.context["labels"])
        if any(labels.get(role) != str(value) for role, value in expected.items()):
            raise ValueError("SVG labels differ from world model")
        image_text = image.decode("utf-8")
        if "2 м" not in image_text or "1 м" not in image_text:
            raise ValueError("SVG scale/path width labels missing")
        if root.attrib.get("viewBox") != "0 0 400 300":
            raise ValueError("SVG scale has changed")
        # Independent measurements in SVG units (10 units = 1 metre).
        plot_area = (320 - 20) * (220 - 20) / 100
        house = ((120, 20), (200, 20), (200, 80), (220, 80), (220, 100), (120, 100))
        area2 = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(house, (*house[1:], house[0]), strict=True)
        )
        house_area = abs(area2) / 2 / 100
        perimeter = (
            sum(
                abs(x2 - x1) + abs(y2 - y1)
                for (x1, y1), (x2, y2) in zip(house, (*house[1:], house[0]), strict=True)
            )
            / 10
        )
        if plot_area != scenario.context["plot_area_m2"]:
            raise ValueError("Plot dimensions and displayed area are inconsistent")
        if house_area != 68 or perimeter != 36:
            raise ValueError("House polygon area/perimeter differ from the task model")
        garden_rect = (80, 100, 200, 200)
        greenhouse_rect = (120, 130, 150, 170)
        if not (
            garden_rect[0] <= greenhouse_rect[0]
            and garden_rect[1] <= greenhouse_rect[1]
            and greenhouse_rect[2] <= garden_rect[2]
            and greenhouse_rect[3] <= garden_rect[3]
        ):
            raise ValueError("Greenhouse must be contained in the garden")


def build_adapter() -> StoryAdapter:
    policy: AnswerPolicy = _Policy()
    families = tuple(
        FamilyRegistration(
            fid,
            i,
            FamilyStatus.ENABLED_CANDIDATE,
            policy.policy_id,
            policy.version,
            enabled=True,
            source_ids=(SOURCE_IDS[i - 1],),
        )
        for i, fid in enumerate(FAMILIES, 1)
    )
    # The non-selected candidate structures remain explicitly unavailable.
    families += tuple(
        FamilyRegistration(
            fid,
            pos,
            status,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=((source,) if source else ()),
        )
        for fid, pos, source, status in (
            ("GARDEN-03-AREA-BUILDING", 3, "366579", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-05-DISTANCE-ORTHOGONAL", 4, "408425", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-06-DISTANCE-DIAGONAL", 4, "366581", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-08-PERCENT-GREENHOUSE", 4, "408433", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-10-PAINT-CHEAPEST", 5, "408450", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-11-OPEN-SOIL", 3, "408430", FamilyStatus.BLOCKED),
            ("GARDEN-12-PERCENT-AREA-DIFF", 4, "", FamilyStatus.RESEARCH_ONLY),
        )
    )
    adapter = type(
        "GardenAdapter",
        (),
        {
            "story_code": "GARDEN",
            "generator": _Generator(),
            "question_builder": _Builder(),
            "independent_oracle": _Oracle(),
            "renderer": _Renderer(),
            "answer_policies": MappingProxyType({(policy.policy_id, policy.version): policy}),
            "family_registry": families,
        },
    )()
    return cast(StoryAdapter, adapter)
