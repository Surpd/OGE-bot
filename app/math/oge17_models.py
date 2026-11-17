"""Local №17 contracts. Exact construction data is separate from float layout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.math.answer_policy import AnswerFormat, AnswerPolicy
from app.math.oge17_additional import FAMILIES as ADDITIONAL_FAMILIES
from app.math.oge17_trapezoids import FAMILIES as TRAPEZOID_FAMILIES

POLICY = AnswerPolicy(
    "oge17.numeric-short",
    "1",
    AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=1,
    max_absolute_value=10000,
    sign="positive",
)

GENERATOR_VERSION = "oge17-quadrilaterals-1"
ORACLE_VERSION = "oge17-coordinate-oracle-1"
RENDERER_VERSION = "oge17-pillow-1"
FAMILIES = tuple(
    f"OGE17-{suffix}" for suffix in ("R03", "E03", "P01", "P07", "T04", "T06", "R02", "P06")
)
CORE_FAMILIES = FAMILIES
FAMILIES += ADDITIONAL_FAMILIES + TRAPEZOID_FAMILIES
# Release: all 16 implemented and verified constructions are available in training.
ENABLED_FAMILIES: tuple[str, ...] = FAMILIES
SOURCES = dict(
    zip(
        CORE_FAMILIES,
        (
            ("356939",),
            ("356927",),
            ("65",),
            ("356914", "438297", "478045"),
            ("323800",),
            ("356717",),
            ("356893",),
            ("356883",),
        ),
        strict=True,
    )
)
SOURCES.update(
    dict(
        zip(ADDITIONAL_FAMILIES, (("356962",), ("323537",), ("356728",), ("314870",)), strict=True)
    )
)
SOURCES.update(
    dict(zip(TRAPEZOID_FAMILIES, (("132776",), ("356704",), ("356777",), ("356873",)), strict=True))
)
Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class QuadrilateralProblem:
    serialized: str

    def to_snapshot(self) -> dict[str, Any]:
        import json

        return dict(json.loads(self.serialized))

    @property
    def fingerprint(self) -> str:
        return str(self.to_snapshot()["fingerprint"])
