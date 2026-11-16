"""Subject-only registry. Importing this module never registers a public training."""

from dataclasses import dataclass
from types import MappingProxyType

from app.math.oge17_models import FAMILIES, GENERATOR_VERSION, SOURCES


@dataclass(frozen=True, slots=True)
class Family:
    family_id: str
    source_ids: tuple[str, ...]
    target: str
    generator_version: str = GENERATOR_VERSION
    public_enabled: bool = False
    source_gate: str = "catalog_text_original_diagram_published_answer_checked"
    acceptance: str = "closed_core_only"


REGISTRY = MappingProxyType(
    {
        family: Family(
            family,
            SOURCES[family],
            target,
            acceptance="HOLD_FINITE_ANGLE_DOMAIN" if family.endswith("R03") else "closed_core_only",
        )
        for family, target in zip(
            FAMILIES, ("ACD", "AC", "area", "DO", "larger_MK_KN", "area"), strict=True
        )
    }
)
