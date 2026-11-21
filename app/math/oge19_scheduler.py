"""Bounded, deterministic task 19 statement-triple scheduler."""

import random
import uuid

from app.math.oge19 import (
    GENERATOR_VERSION,
    POLICY,
    NoCompatibleTriple,
    generate,
    refresh_snapshot_digest,
)

FAMILY_THEMES = {
    "OGE19-MIXED": "mixed",
    "OGE19-TRIANGLES": "triangles",
    "OGE19-QUADRILATERALS": "quadrilaterals",
    "OGE19-CIRCLES": "circles",
    "OGE19-LINES-ANGLES": "lines_angles",
    "OGE19-AREAS-METRICS": "areas_metrics",
}
ENABLED_FAMILIES: tuple[str, ...] = tuple(FAMILY_THEMES)  # Public release of OGE #19.


def build_task19_candidate_batch(
    state: dict[str, object], seed: int, *, enabled_families: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    families = ENABLED_FAMILIES if enabled_families is None else enabled_families
    stored = state.get("family_queue")
    queue = [family for family in stored if family in families] if isinstance(stored, list) else []
    rng = random.Random(seed)
    if not queue:
        queue = list(families)
        rng.shuffle(queue)
        if len(queue) > 1 and queue[0] == state.get("last_family_id"):
            queue[0], queue[1] = queue[1], queue[0]
    if not queue:
        return []
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
    fingerprints = state.get("recent_fingerprints", [])
    seen = (
        set(x for x in fingerprints if isinstance(x, str))
        if isinstance(fingerprints, list)
        else set()
    )
    for attempt in range(12):
        candidate_seed = seed if attempt == 0 else rng.getrandbits(63)
        try:
            triple = generate(
                candidate_seed,
                theme=theme,
                recent_proposition_ids=recent_ids if attempt < 4 else recent_ids[-9:],
                correct_position_counts=position_counts,
                excluded_fingerprints=frozenset(seen) if attempt else frozenset(),
            )
        except NoCompatibleTriple:
            continue
        proposition_ids = [item.proposition_id for item in triple.statements]
        fingerprint = ":".join(sorted(proposition_ids))
        if fingerprint not in seen:
            break
    else:
        return []
    snapshot = triple.snapshot()
    condition = "Какие из следующих утверждений верны? В ответ запишите их номера.\n\n" + "\n".join(
        f"{i}. {item.statement}" for i, item in enumerate(triple.statements, 1)
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
            "problem_id": str(uuid.uuid4()),
            "family_id": family,
            "generator_version": GENERATOR_VERSION,
            "seed": candidate_seed,
            "correct_answer": answer,
            "answer_policy_id": POLICY.policy_id,
            "answer_policy_version": POLICY.version,
            "condition": condition,
            "solution": solution,
            "hints": hints,
            "fingerprint": fingerprint,
            "selection_attempts": attempt + 1,
            "atomic_proposition_ids": proposition_ids,
            "_recent_proposition_ids_after": [*recent_ids, *proposition_ids][-30:],
            "_correct_position_counts_after": [
                position_counts[i] + (1 if str(i + 1) in answer else 0) for i in range(3)
            ],
            "_family_queue_after": queue[1:],
            "_last_family_after": family,
        }
    )
    refresh_snapshot_digest(snapshot)
    return [snapshot]
