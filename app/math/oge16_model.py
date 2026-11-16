"""Serializable geometry, independent of Telegram and rasterization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class CircleGeometry:
    radius: float
    points: tuple[tuple[str, Point], ...]
    segments: tuple[tuple[str, str], ...]
    center: Point = (0.0, 0.0)
    # A02 explicitly identifies the counterclockwise minor A→B arc, excluding C.
    arc: tuple[str, str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "radius": self.radius,
            "center": list(self.center),
            "points": {name: list(point) for name, point in self.points},
            "segments": [list(segment) for segment in self.segments],
            "arc": list(self.arc) if self.arc else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircleGeometry:
        return cls(
            radius=float(data["radius"]),
            center=tuple(data["center"]),
            points=tuple((name, tuple(point)) for name, point in data["points"].items()),
            segments=tuple(tuple(pair) for pair in data["segments"]),
            arc=tuple(data["arc"]) if data["arc"] else None,
        )
