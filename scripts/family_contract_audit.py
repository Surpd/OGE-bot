"""Check generated variants and summarize template risks without contacting Telegram."""

import json
from collections import Counter, defaultdict

from app.bot.math_notation import rich_needs_png_fallback
from app.bot.part2 import solution_text, statement_text
from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.bot.task_view import question_text
from app.math.generator import training_rejection
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.persistence.part2_bank import ATLAS
from scripts.oge_bank_quality_audit import _oracle, _ordinary_generator


def story_samples():
    counts = defaultdict(Counter)
    for story, families in PUBLIC_FAMILIES.items():
        for seed in range(1000):
            scene = build_practice_plan(
                PracticeRequest(PracticeMode.FULL, seed, story), public_registry()
            ).snapshot
            for question in scene.questions:
                row = counts[question.family_id]
                if row["variants"] < 32:
                    row["variants"] += 1
                    texts = [
                        scene.shared_context,
                        question.condition,
                        *question.hints,
                        *question.solution_steps,
                        question.canonical_answer,
                    ]
                    row["unsafe_variants"] += any(map(rich_needs_png_fallback, texts))
            if all(counts[f]["variants"] == 32 for f in families):
                break
        else:
            raise ValueError(story)
    return counts


def main():
    counts = defaultdict(Counter)
    for number in range(6, 20):
        families, generate = _ordinary_generator(number)
        for family in families:
            for seed in range(32):
                item = generate(family, seed)
                assert _oracle(number, family, item), (number, family, seed)
                data = item.to_snapshot()
                row = counts[family]
                row["variants"] += 1
                if number == 6 and (reason := training_rejection(item)):
                    row[reason] += 1
                steps = data["solution"]
                texts = [
                    question_text(number, data),
                    *data["hints"],
                    *(steps if isinstance(steps, list) else [steps]),
                ]
                row["unsafe_variants"] += any(map(rich_needs_png_fallback, texts))
    for family, stats in story_samples().items():
        counts[family].update(stats)
    for card in map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()):
        row = counts[card["subtype_id"]]
        row["variants"] += 1
        row["unsafe_variants"] += any(
            map(
                rich_needs_png_fallback,
                [
                    statement_text(card),
                    *card["hints"],
                    solution_text(card),
                    card["answer_or_claim"],
                ],
            )
        )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
