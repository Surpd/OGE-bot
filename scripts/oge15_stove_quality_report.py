"""Run deterministic per-family and compatible-bundle quality gates for STOVE."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.math.scenario_engine import QuestionDraft
from app.math.scenarios.stories.STOVE import FAMILY_IDS, SOURCE_IDS, build_adapter


def run(samples: int) -> dict[str, Any]:
    if samples < 250:
        raise ValueError("The STOVE main quality run requires at least 250 samples per family")
    adapter = build_adapter()
    per_family: dict[str, dict[str, Any]] = {}
    full_bundles = 0
    bundle_fingerprints: set[str] = set()

    for family_id in FAMILY_IDS:
        position = next(
            reg.position for reg in adapter.family_registry if reg.family_id == family_id
        )
        fingerprints: set[str] = set()
        answers: Counter[str] = Counter()
        for offset in range(samples):
            seed = 50_000 + offset
            scenario = adapter.generator.generate_scenario(seed)
            adapter.independent_oracle.validate_scenario(scenario)
            rendered = adapter.renderer.render_scenario(scenario)
            question = adapter.question_builder.build_question_for_family(
                scenario, position, family_id
            )
            adapter.independent_oracle.validate_question(scenario, question, rendered)
            fingerprint_data = f"{family_id}\n{question.condition}\n{rendered.shared_context}"
            fingerprints.add(sha256(fingerprint_data.encode("utf-8")).hexdigest())
            answers[question.canonical_answer] += 1
        if len(fingerprints) < 200:
            raise AssertionError(
                f"{family_id} produced only {len(fingerprints)} unique visible tasks"
            )
        per_family[family_id] = {
            "samples": samples,
            "independent_oracle_passes": samples,
            "unique_visible_fingerprints": len(fingerprints),
            "answer_value_count": len(answers),
            "source_ids": list(SOURCE_IDS[family_id]),
            "enabled_for_students": False,
            "status": "enabled_candidate",
        }

    # Explicitly exercise the exact five-position compatibility requirement on
    # every sample seed; the stochastic family plan is deterministic per seed.
    for offset in range(samples):
        seed = 50_000 + offset
        scenario = adapter.generator.generate_scenario(seed)
        adapter.independent_oracle.validate_scenario(scenario)
        rendered = adapter.renderer.render_scenario(scenario)
        questions: tuple[QuestionDraft, ...] = tuple(
            adapter.question_builder.build_question(scenario, position) for position in range(1, 6)
        )
        adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
        bundle_fingerprints.add(
            sha256(
                (
                    rendered.shared_context + "\n" + "\n".join(q.condition for q in questions)
                ).encode()
            ).hexdigest()
        )
        full_bundles += 1

    return {
        "story_code": "STOVE",
        "generator_version": "stove-v1.0",
        "renderer_version": "stove-svg-png-v1",
        "sample_count_per_family": samples,
        "family_count": len(per_family),
        "families": per_family,
        "full_compatible_bundles": full_bundles,
        "unique_full_bundle_fingerprints": len(bundle_fingerprints),
        "all_family_gates_passed": all(
            v["unique_visible_fingerprints"] >= 200 for v in per_family.values()
        ),
        "student_enablement": "disabled_pending_separate_release_review",
        "known_exclusions": [
            "STOVE-F13-YEARLY-OPERATING-COSTS: source wording/target operation not confirmed",
            "STOVE-F14-UNVERIFIED-ARC-DESIGNS: source 408261 has a conflicted answer key/figure",
            "STOVE-F15-BROKEN-PRICE-KEY: source 408240 has a conflicted answer key",
            "Research V1 covers a partial set of catalog observations, not the full official bank.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=250)
    parser.add_argument("--output", type=Path, default=Path("reports/oge15-stove-quality.json"))
    args = parser.parse_args()
    result = run(args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {args.output}; {args.samples} per family; {result['full_compatible_bundles']} bundles"  # noqa: E501
    )


if __name__ == "__main__":
    main()
