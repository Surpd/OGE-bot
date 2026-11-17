"""Bounded, deterministic task 19 statement-triple scheduler."""

import random
import uuid

from app.math.oge19 import GENERATOR_VERSION, POLICY, generate, refresh_snapshot_digest

FAMILY_THEMES = {
    "OGE19-MIXED": "mixed",
    "OGE19-TRIANGLES": "triangles",
    "OGE19-QUADRILATERALS": "quadrilaterals",
    "OGE19-CIRCLES": "circles",
    "OGE19-LINES-ANGLES": "lines_angles",
    "OGE19-AREAS-METRICS": "areas_metrics",
}
ENABLED_FAMILIES: tuple[str, ...] = ()  # Public menu activation awaits final acceptance.


def build_task19_candidate_batch(
    state: dict[str, object], seed: int, *, enabled_families: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    families = ENABLED_FAMILIES if enabled_families is None else enabled_families
    stored = state.get("family_queue")
    queue = [family for family in stored if family in families] if isinstance(stored, list) else []
    rng = random.Random(seed)
    if not queue:
        if "OGE19-MIXED" in families:
            queue = ["OGE19-MIXED"]
        else:
            queue = list(families)
            rng.shuffle(queue)
    if not queue:
        # Internal QA and deterministic builder callers can opt in; ordinary menu stays disabled.
        queue = ["OGE19-MIXED"]
        families = tuple(FAMILY_THEMES)
    family = queue[0]
    theme = FAMILY_THEMES[family]
    recent = state.get("recent_proposition_ids", [])
    recent_ids = (
        tuple(x for x in recent if isinstance(x, str))[-30:] if isinstance(recent, list) else ()
    )
    counts = state.get("correct_position_counts", [0, 0, 0])
    position_counts = (
        tuple(counts[:3]) if isinstance(counts, list) and len(counts) >= 3 else (0, 0, 0)
    )
    triple = generate(
        seed,
        theme=theme,
        recent_proposition_ids=recent_ids,
        correct_position_counts=position_counts,
    )
    snapshot = triple.snapshot()
    proposition_ids = [item.proposition_id for item in triple.statements]
    condition = (
        "Какое из следующих утверждений является истинным высказыванием?\n\n"
        + "\n".join(f"{i}. {item.statement}" for i, item in enumerate(triple.statements, 1))
        + "\n\nВ ответ запишите номер истинного высказывания."
    )
    answer = triple.answer_mask
    hints = [
        (
            "Проверьте, какие условия нужны для каждого известного признака или свойства. "
            "Обратное утверждение может быть неверным."
        ),
        (
            "Рассмотрите отдельно каждый пункт: для общего утверждения достаточно проверить "
            "теорему, а для опровержения найти допустимый контрпример."
        ),
    ]
    solution = [
        f"{i}. {'Верно' if item.is_true else 'Неверно'}: {item.explanation}"
        for i, item in enumerate(triple.statements, 1)
    ]
    snapshot.update(
        {
            "problem_id": str(uuid.UUID(int=seed % (1 << 128))),
            "family_id": family,
            "generator_version": GENERATOR_VERSION,
            "seed": seed,
            "correct_answer": answer,
            "answer_policy_id": POLICY.policy_id,
            "answer_policy_version": POLICY.version,
            "condition": condition,
            "solution": solution,
            "hints": hints,
            "fingerprint": ":".join(sorted(proposition_ids)),
            "selection_attempts": 1,
            "atomic_proposition_ids": proposition_ids,
            "_recent_proposition_ids_after": [*recent_ids, *proposition_ids][-30:],
            "_correct_position_counts_after": [
                position_counts[i] + (1 if answer == str(i + 1) else 0) for i in range(3)
            ],
            "_family_queue_after": queue[1:],
            "_last_family_after": family,
        }
    )
    refresh_snapshot_digest(snapshot)
    return [snapshot]
