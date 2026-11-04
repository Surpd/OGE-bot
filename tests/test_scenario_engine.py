from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from app.math.scenario_engine import (
    FamilyRegistration,
    FamilyRegistry,
    FamilyStatus,
    PracticeMode,
    PracticeRequest,
    QuestionDraft,
    RenderedScenario,
    ScenarioAssetRef,
    ScenarioDraft,
    ScenarioSnapshot,
    ScenarioUnavailable,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)


class _Policy:
    policy_id = "test.number"
    version = "1"

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        return raw_answer == canonical_answer


class _Adapter:
    story_code = "PAPER"

    def __init__(self, enabled_positions: tuple[int, ...] = (1, 2, 3, 4, 5)) -> None:
        self.render_calls = 0
        self.oracle_calls = 0
        self.generator = self
        self.question_builder = self
        self.independent_oracle = self
        self.renderer = self
        self.answer_policies = {("test.number", "1"): _Policy()}
        self.family_registry = tuple(
            FamilyRegistration(
                family_id=f"PAPER-F{position:02}",
                position=position,
                status=FamilyStatus.ENABLED_CANDIDATE,
                answer_policy_id="test.number",
                answer_policy_version="1",
                enabled=position in enabled_positions,
                source_ids=(f"test-{position}",),
            )
            for position in range(1, 6)
        )

    def generate_scenario(self, seed: int) -> ScenarioDraft:
        return ScenarioDraft("PAPER", seed, "test-v1", {"table": [[1, 2]]}, "matrix-v1")

    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        return QuestionDraft(
            position=position,
            scenario_seed=scenario.seed,
            family_id=f"PAPER-F{position:02}",
            generator_version="test-v1",
            condition=f"Question {position}",
            answer_policy_id="test.number",
            answer_policy_version="1",
            canonical_answer=str(position),
            hints=("hint",),
            solution_steps=("step",),
            math_model={"result": position},
        )

    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        self.render_calls += 1
        return RenderedScenario("Shared context")

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        raise NotImplementedError

    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        assert scenario.seed >= 0

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        assert question.scenario_seed == scenario.seed
        assert rendered.shared_context == "Shared context"
        self.oracle_calls += 1

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        assert all(question.scenario_seed == scenario.seed for question in questions)
        assert rendered.shared_context == "Shared context"


def test_story_registry_discovery_stays_fail_closed_until_families_are_enabled() -> None:
    assert FamilyRegistry().available_stories(PracticeMode.FULL) == ()
    registry = discover_story_registry()
    assert registry.available_stories(PracticeMode.FULL) == ()
    for story_code in registry.story_codes:
        assert all(not family.available for family in registry.adapter(story_code).family_registry)
    from app.bot.trainings import BY_NUMBER

    assert not any(number in BY_NUMBER for number in range(1, 6))
    with pytest.raises(ScenarioUnavailable, match="No enabled"):
        build_practice_plan(PracticeRequest(PracticeMode.FULL, seed=10), FamilyRegistry())


def test_full_plan_builds_one_context_and_five_same_seed_questions() -> None:
    adapter = _Adapter()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=51, story_code="PAPER"),
        FamilyRegistry((adapter,)),
    )

    assert plan.selected_positions == (1, 2, 3, 4, 5)
    assert [question.position for question in plan.snapshot.questions] == [1, 2, 3, 4, 5]
    assert {question.scenario_seed for question in plan.snapshot.questions} == {51}
    assert adapter.render_calls == 1
    assert adapter.oracle_calls == 5
    with pytest.raises(TypeError):
        plan.snapshot.context["table"] = ()  # type: ignore[index]


def test_single_plan_keeps_shared_scenario_but_selects_one_question() -> None:
    adapter = _Adapter()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, seed=75, story_code="PAPER", position=4),
        FamilyRegistry((adapter,)),
    )
    assert plan.selected_positions == (4,)
    assert len(plan.snapshot.questions) == 5
    assert tuple(question.position for question in plan.snapshot.questions) == (1, 2, 3, 4, 5)
    assert adapter.oracle_calls == 5
    assert plan.snapshot.shared_context == "Shared context"
    assert adapter.render_calls == 1


def test_incompatible_or_disabled_family_fails_closed() -> None:
    adapter = _Adapter(enabled_positions=(1, 2, 3, 4))
    registry = FamilyRegistry((adapter,))
    assert registry.available_stories(PracticeMode.FULL) == ()
    with pytest.raises(ScenarioUnavailable, match="no enabled family"):
        build_practice_plan(
            PracticeRequest(PracticeMode.SINGLE, seed=3, story_code="PAPER", position=5), registry
        )


def test_snapshot_roundtrip_and_seed_mixing_guard() -> None:
    adapter = _Adapter()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=26, story_code="PAPER"),
        FamilyRegistry((adapter,)),
    )
    restored = type(plan.snapshot).from_snapshot(plan.snapshot.to_snapshot())
    assert restored == plan.snapshot
    with pytest.raises(ValueError, match="same scenario seed"):
        type(plan.snapshot)(
            story_code="PAPER",
            seed=26,
            generator_version="test-v1",
            compatibility_matrix_version="matrix-v1",
            context={"table": []},
            shared_context="Shared context",
            assets=(),
            questions=(
                plan.snapshot.questions[0],
                replace(plan.snapshot.questions[1], scenario_seed=27),
                *plan.snapshot.questions[2:],
            ),
        )


def test_asset_bytes_restore_deterministically_and_are_digest_checked() -> None:
    adapter = _Adapter()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=26, story_code="PAPER"),
        FamilyRegistry((adapter,)),
    )
    content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    digest = sha256(content).hexdigest()
    asset = ScenarioAssetRef(digest, "image/svg+xml", f"sha256/{digest}.svg")
    snapshot = replace(plan.snapshot, assets=(asset,))

    class _Renderer:
        def restore_asset(
            self, stored_snapshot: ScenarioSnapshot, reference: ScenarioAssetRef
        ) -> bytes:
            assert stored_snapshot is snapshot
            assert reference == asset
            return content

    assert restore_asset_bytes(_Renderer(), snapshot, asset) == content

    class _CorruptRenderer(_Renderer):
        def restore_asset(
            self, stored_snapshot: ScenarioSnapshot, reference: ScenarioAssetRef
        ) -> bytes:
            return b"different bytes"

    with pytest.raises(ValueError, match="digest does not match"):
        restore_asset_bytes(_CorruptRenderer(), snapshot, asset)


def test_generated_question_seed_mismatch_is_rejected() -> None:
    class WrongSeedAdapter(_Adapter):
        def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
            question = super().build_question(scenario, position)
            return QuestionDraft(
                position=question.position,
                scenario_seed=scenario.seed + 1,
                family_id=question.family_id,
                generator_version=question.generator_version,
                condition=question.condition,
                answer_policy_id=question.answer_policy_id,
                answer_policy_version=question.answer_policy_version,
                canonical_answer=question.canonical_answer,
                hints=question.hints,
                solution_steps=question.solution_steps,
                math_model=question.math_model,
            )

    with pytest.raises(ValueError, match="mismatched position or scenario seed"):
        build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed=9, story_code="PAPER"),
            FamilyRegistry((WrongSeedAdapter(),)),
        )
