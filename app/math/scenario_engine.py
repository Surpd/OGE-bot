"""Shared, fail-closed contracts for OGE practice scenarios 1–5.

Story modules implement these protocols; this module contains no story math.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonValue, ...] | Mapping[str, JsonValue]
STORY_CODES = ("TYRES", "PAPER", "STOVE", "TARIFF", "ROUTE", "GARDEN", "FLAT")
POSITIONS = (1, 2, 3, 4, 5)


class PracticeMode(StrEnum):
    SINGLE = "single"
    FULL = "full"


class FamilyStatus(StrEnum):
    ENABLED_CANDIDATE = "enabled_candidate"
    RESEARCH_ONLY = "research_only"
    BLOCKED = "blocked"


class ScenarioUnavailable(RuntimeError):
    """No registered, student-enabled family can satisfy the requested mode."""


def _freeze_json(value: object) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Scenario snapshot data cannot contain non-finite numbers")
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError("Scenario snapshot data must contain only JSON values")


def _json_copy(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_copy(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ScenarioDraft:
    story_code: str
    seed: int
    generator_version: str
    context: Mapping[str, JsonValue]
    compatibility_matrix_version: str
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.story_code not in STORY_CODES:
            raise ValueError("Unknown OGE 1–5 story code")
        if not 0 <= self.seed < 2**63:
            raise ValueError("Scenario seed must fit a non-negative PostgreSQL bigint")
        if not self.generator_version or not self.compatibility_matrix_version:
            raise ValueError("Scenario versions must be non-empty")
        object.__setattr__(self, "context", _freeze_json(self.context))
        if not isinstance(self.context, Mapping):
            raise TypeError("Scenario context must be a JSON object")
        object.__setattr__(self, "provenance", tuple(self.provenance))


@dataclass(frozen=True, slots=True)
class ScenarioAssetRef:
    sha256: str
    content_type: str
    storage_key: str

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("Scenario assets require a lowercase SHA-256 digest")
        if not self.content_type or not self.storage_key:
            raise ValueError("Scenario assets require a content type and storage key")


@dataclass(frozen=True, slots=True)
class QuestionDraft:
    position: int
    scenario_seed: int
    family_id: str
    generator_version: str
    condition: str
    answer_policy_id: str
    answer_policy_version: str
    canonical_answer: str
    hints: tuple[str, ...]
    solution_steps: tuple[str, ...]
    math_model: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError("Question position must be from 1 through 5")
        if not self.family_id or not self.generator_version:
            raise ValueError("Questions require a family and generator version")
        if not self.condition.strip() or not self.canonical_answer.strip():
            raise ValueError("Questions require visible condition and answer")
        if not self.answer_policy_id or not self.answer_policy_version:
            raise ValueError("Question answer policy id and version are required")
        object.__setattr__(self, "hints", tuple(self.hints))
        object.__setattr__(self, "solution_steps", tuple(self.solution_steps))
        object.__setattr__(self, "math_model", _freeze_json(self.math_model))


@dataclass(frozen=True, slots=True)
class QuestionSnapshot:
    position: int
    scenario_seed: int
    family_id: str
    generator_version: str
    condition: str
    answer_policy_id: str
    answer_policy_version: str
    canonical_answer: str
    hints: tuple[str, ...]
    solution_steps: tuple[str, ...]
    math_model: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError("Question snapshot position must be from 1 through 5")
        if not self.family_id or not self.generator_version:
            raise ValueError("Question snapshots require a family and generator version")
        if not self.condition.strip() or not self.canonical_answer.strip():
            raise ValueError("Question snapshots require visible condition and answer")
        if not self.answer_policy_id or not self.answer_policy_version:
            raise ValueError("Question snapshot answer policy id and version are required")
        object.__setattr__(self, "hints", tuple(self.hints))
        object.__setattr__(self, "solution_steps", tuple(self.solution_steps))
        math_model = _freeze_json(self.math_model)
        if not isinstance(math_model, Mapping):
            raise TypeError("Question snapshot math model must be a JSON object")
        object.__setattr__(self, "math_model", math_model)

    @classmethod
    def from_draft(cls, draft: QuestionDraft) -> QuestionSnapshot:
        return cls(**{field: getattr(draft, field) for field in cls.__dataclass_fields__})

    def to_snapshot(self) -> dict[str, object]:
        return {
            "position": self.position,
            "scenario_seed": self.scenario_seed,
            "family_id": self.family_id,
            "generator_version": self.generator_version,
            "condition": self.condition,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "canonical_answer": self.canonical_answer,
            "hints": list(self.hints),
            "solution_steps": list(self.solution_steps),
            "math_model": _json_copy(self.math_model),
        }


@dataclass(frozen=True, slots=True)
class RenderedScenario:
    """One rendered shared context. Binary media is stored by digest, never inline."""

    shared_context: str
    assets: tuple[ScenarioAssetRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.shared_context.strip():
            raise ValueError("Renderer must return a non-empty shared context")
        object.__setattr__(self, "assets", tuple(self.assets))
        if len({asset.sha256 for asset in self.assets}) != len(self.assets):
            raise ValueError("A shared scenario must reference each image digest once")


@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    story_code: str
    seed: int
    generator_version: str
    compatibility_matrix_version: str
    context: Mapping[str, JsonValue]
    shared_context: str
    assets: tuple[ScenarioAssetRef, ...]
    questions: tuple[QuestionSnapshot, ...]
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.story_code not in STORY_CODES:
            raise ValueError("Unknown OGE 1–5 story code")
        if not 0 <= self.seed < 2**63:
            raise ValueError("Scenario seed must fit a non-negative PostgreSQL bigint")
        object.__setattr__(self, "context", _freeze_json(self.context))
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "questions", tuple(self.questions))
        object.__setattr__(self, "provenance", tuple(self.provenance))
        positions = tuple(question.position for question in self.questions)
        if positions not in (POSITIONS,) and (
            len(positions) != 1 or positions[0] not in POSITIONS
        ):
            raise ValueError(
                "A snapshot must contain one selected question or the full ordered set"
            )
        if any(question.scenario_seed != self.seed for question in self.questions):
            raise ValueError("All snapshot questions must use the scenario seed")
        if not self.shared_context.strip():
            raise ValueError("Scenario snapshot must preserve the rendered shared context")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "story_code": self.story_code,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "compatibility_matrix_version": self.compatibility_matrix_version,
            "context": _json_copy(self.context),
            "shared_context": self.shared_context,
            "assets": [
                {
                    "sha256": item.sha256,
                    "content_type": item.content_type,
                    "storage_key": item.storage_key,
                }
                for item in self.assets
            ],
            "questions": [item.to_snapshot() for item in self.questions],
            "provenance": list(self.provenance),
        }

    @classmethod
    def from_snapshot(cls, value: Mapping[str, object]) -> ScenarioSnapshot:
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported scenario snapshot schema version")
        raw_questions = value.get("questions")
        raw_assets = value.get("assets")
        context = value.get("context")
        raw_provenance = value.get("provenance", [])
        if not isinstance(raw_questions, list) or not isinstance(raw_assets, list):
            raise ValueError("Scenario snapshot questions and assets must be arrays")
        if not isinstance(context, Mapping):
            raise ValueError("Scenario snapshot context must be an object")
        if not isinstance(raw_provenance, list):
            raise ValueError("Scenario snapshot provenance must be an array")
        questions: list[QuestionSnapshot] = []
        for raw in raw_questions:
            if not isinstance(raw, Mapping):
                raise ValueError("Scenario question snapshot must be an object")
            raw_hints = raw.get("hints")
            raw_steps = raw.get("solution_steps")
            raw_model = raw.get("math_model")
            if not isinstance(raw_hints, list) or not isinstance(raw_steps, list):
                raise ValueError("Scenario question hints and steps must be arrays")
            math_model = _freeze_json(raw_model)
            if not isinstance(math_model, Mapping):
                raise ValueError("Scenario question math model must be an object")
            questions.append(
                QuestionSnapshot(
                    position=int(raw["position"]),
                    scenario_seed=int(raw["scenario_seed"]),
                    family_id=str(raw["family_id"]),
                    generator_version=str(raw["generator_version"]),
                    condition=str(raw["condition"]),
                    answer_policy_id=str(raw["answer_policy_id"]),
                    answer_policy_version=str(raw["answer_policy_version"]),
                    canonical_answer=str(raw["canonical_answer"]),
                    hints=tuple(str(item) for item in raw_hints),
                    solution_steps=tuple(str(item) for item in raw_steps),
                    math_model=math_model,
                )
            )
        assets = tuple(
            ScenarioAssetRef(
                sha256=str(raw["sha256"]),
                content_type=str(raw["content_type"]),
                storage_key=str(raw["storage_key"]),
            )
            for raw in raw_assets
            if isinstance(raw, Mapping)
        )
        if len(assets) != len(raw_assets):
            raise ValueError("Scenario asset reference must be an object")
        frozen_context = _freeze_json(context)
        if not isinstance(frozen_context, Mapping):
            raise ValueError("Scenario snapshot context must be an object")
        return cls(
            story_code=str(value["story_code"]),
            seed=int(value["seed"]),
            generator_version=str(value["generator_version"]),
            compatibility_matrix_version=str(value["compatibility_matrix_version"]),
            context=frozen_context,
            shared_context=str(value["shared_context"]),
            assets=assets,
            questions=tuple(questions),
            provenance=tuple(str(item) for item in raw_provenance),
        )


@dataclass(frozen=True, slots=True)
class FamilyRegistration:
    family_id: str
    position: int
    status: FamilyStatus
    answer_policy_id: str
    answer_policy_version: str
    enabled: bool = False
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.family_id or not self.answer_policy_id or not self.answer_policy_version:
            raise ValueError("Family registration requires family and answer policy identifiers")
        if self.position not in POSITIONS:
            raise ValueError("Registered family position must be from 1 through 5")
        if not isinstance(self.status, FamilyStatus):
            object.__setattr__(self, "status", FamilyStatus(self.status))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))

    @property
    def available(self) -> bool:
        return self.status is FamilyStatus.ENABLED_CANDIDATE and self.enabled


class ScenarioGenerator(Protocol):
    def generate_scenario(self, seed: int) -> ScenarioDraft: ...


class QuestionBuilder(Protocol):
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft: ...


class IndependentOracle(Protocol):
    def validate_scenario(self, scenario: ScenarioDraft) -> None: ...

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None: ...

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None: ...


class Renderer(Protocol):
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario: ...


class AnswerPolicy(Protocol):
    @property
    def policy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool: ...


class StoryAdapter(Protocol):
    story_code: str
    generator: ScenarioGenerator
    question_builder: QuestionBuilder
    independent_oracle: IndependentOracle
    renderer: Renderer
    answer_policies: Mapping[tuple[str, str], AnswerPolicy]
    family_registry: tuple[FamilyRegistration, ...]


class FamilyRegistry:
    """Registry of installed story adapters. Empty until real modules are added."""

    def __init__(self, adapters: Sequence[StoryAdapter] = ()) -> None:
        by_code: dict[str, StoryAdapter] = {}
        for adapter in adapters:
            code = adapter.story_code
            if code not in STORY_CODES or code in by_code:
                raise ValueError("Story adapters must use unique, supported story codes")
            registrations = adapter.family_registry
            if len({item.family_id for item in registrations}) != len(registrations):
                raise ValueError(f"Duplicate family id in {code} registry")
            for family in registrations:
                if family.position not in POSITIONS:
                    raise ValueError("Registered family position must be from 1 through 5")
                policy = adapter.answer_policies.get(
                    (family.answer_policy_id, family.answer_policy_version)
                )
                if family.available and policy is None:
                    raise ValueError(f"Enabled family {family.family_id} has no answer policy")
                if family.available and not family.source_ids:
                    raise ValueError(f"Enabled family {family.family_id} has no source references")
            by_code[code] = adapter
        self._adapters = MappingProxyType(by_code)

    @property
    def story_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def adapter(self, story_code: str) -> StoryAdapter:
        try:
            return self._adapters[story_code]
        except KeyError as error:
            raise ScenarioUnavailable(f"Story {story_code} is not installed") from error

    def available_positions(self, story_code: str) -> tuple[int, ...]:
        adapter = self.adapter(story_code)
        return tuple(
            position
            for position in POSITIONS
            if any(
                family.position == position and family.available
                for family in adapter.family_registry
            )
        )

    def available_stories(self, mode: PracticeMode, position: int | None = None) -> tuple[str, ...]:
        if mode is PracticeMode.SINGLE and position is not None and position not in POSITIONS:
            raise ValueError("Single-task position must be from 1 through 5")
        if mode is PracticeMode.FULL and position is not None:
            raise ValueError("Full mode does not accept an individual position")
        result = []
        for code in self.story_codes:
            available = self.available_positions(code)
            if (mode is PracticeMode.FULL and available == POSITIONS) or (
                mode is PracticeMode.SINGLE and (position is None or position in available)
            ):
                result.append(code)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class PracticeRequest:
    mode: PracticeMode
    seed: int
    story_code: str | None = None
    position: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, PracticeMode):
            object.__setattr__(self, "mode", PracticeMode(self.mode))
        if not 0 <= self.seed < 2**63:
            raise ValueError("Practice seed must fit a non-negative PostgreSQL bigint")
        if self.story_code is not None and self.story_code not in STORY_CODES:
            raise ValueError("Unsupported story selection")
        if self.mode is PracticeMode.FULL and self.position is not None:
            raise ValueError("Full mode always includes all five questions")
        if self.position is not None and self.position not in POSITIONS:
            raise ValueError("Single-task position must be from 1 through 5")


@dataclass(frozen=True, slots=True)
class PracticePlan:
    mode: PracticeMode
    snapshot: ScenarioSnapshot
    selected_positions: tuple[int, ...]


def build_practice_plan(request: PracticeRequest, registry: FamilyRegistry) -> PracticePlan:
    """Build and independently validate one immutable scenario and its selected questions."""
    available = registry.available_stories(request.mode, request.position)
    if request.story_code is not None:
        if request.story_code not in available:
            raise ScenarioUnavailable("Selected story has no enabled family for this mode")
        story_code = request.story_code
    else:
        if not available:
            raise ScenarioUnavailable("No enabled OGE 1–5 story adapters are installed")
        story_code = random.Random(request.seed).choice(available)

    adapter = registry.adapter(story_code)
    scenario = adapter.generator.generate_scenario(request.seed)
    if scenario.story_code != story_code or scenario.seed != request.seed:
        raise ValueError("Scenario generator returned a different story or seed")
    adapter.independent_oracle.validate_scenario(scenario)
    rendered = adapter.renderer.render_scenario(scenario)
    if request.mode is PracticeMode.FULL:
        selected_positions = POSITIONS
    elif request.position is not None:
        selected_positions = (request.position,)
    else:
        eligible_positions = registry.available_positions(story_code)
        if not eligible_positions:
            raise ScenarioUnavailable("Selected story has no enabled question positions")
        selected_positions = (random.Random(request.seed ^ 0x15).choice(eligible_positions),)

    questions: list[QuestionSnapshot] = []
    draft_questions: list[QuestionDraft] = []
    for position in selected_positions:
        question = adapter.question_builder.build_question(scenario, position)
        if question.position != position or question.scenario_seed != scenario.seed:
            raise ValueError("Question builder returned a mismatched position or scenario seed")
        registrations = [
            family
            for family in adapter.family_registry
            if family.position == position and family.family_id == question.family_id
        ]
        if len(registrations) != 1 or not registrations[0].available:
            raise ScenarioUnavailable(f"Question family at position {position} is disabled")
        if (
            question.answer_policy_id != registrations[0].answer_policy_id
            or question.answer_policy_version != registrations[0].answer_policy_version
        ):
            raise ValueError("Question answer policy differs from its registered family policy")
        policy = adapter.answer_policies.get(
            (question.answer_policy_id, question.answer_policy_version)
        )
        if policy is None:
            raise ValueError("Question references an unregistered answer policy version")
        adapter.independent_oracle.validate_question(scenario, question, rendered)
        draft_questions.append(question)
        questions.append(QuestionSnapshot.from_draft(question))

    adapter.independent_oracle.validate_bundle(scenario, tuple(draft_questions), rendered)

    snapshot = ScenarioSnapshot(
        story_code=scenario.story_code,
        seed=scenario.seed,
        generator_version=scenario.generator_version,
        compatibility_matrix_version=scenario.compatibility_matrix_version,
        context=scenario.context,
        shared_context=rendered.shared_context,
        assets=rendered.assets,
        questions=tuple(questions),
        provenance=scenario.provenance,
    )
    return PracticePlan(request.mode, snapshot, selected_positions)


def snapshot_digest(snapshot: ScenarioSnapshot) -> str:
    encoded = json.dumps(
        snapshot.to_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def discover_story_registry() -> FamilyRegistry:
    """Load independent ``stories/<CODE>.py`` modules without central registry edits."""
    from importlib import import_module
    from pkgutil import iter_modules

    package = import_module("app.math.scenarios.stories")
    adapters: list[StoryAdapter] = []
    seen_codes: set[str] = set()
    for module_info in iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = import_module(f"{package.__name__}.{module_info.name}")
        factory = getattr(module, "build_adapter", None)
        if not callable(factory):
            raise TypeError(f"Story module {module_info.name} must expose build_adapter()")
        adapter = factory()
        if adapter.story_code in seen_codes:
            raise ValueError(f"More than one module registered story {adapter.story_code}")
        seen_codes.add(adapter.story_code)
        adapters.append(adapter)
    return FamilyRegistry(adapters)
