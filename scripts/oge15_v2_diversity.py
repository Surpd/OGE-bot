"""Summarize observed question diversity without counting seed or asset identity."""

from collections import Counter, defaultdict

from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.recent_questions import question_signature

SAMPLES = 64


def main() -> None:
    registry = public_registry()
    print("# V2. Наблюдаемое разнообразие")
    print()
    print(f"Проба из {SAMPLES} seed (0–{SAMPLES - 1}) на сюжет. Это наблюдение, не предел ёмкости.")
    print("Сигнатура учитывает условие и существенные исходные данные из схем и таблиц.")
    print("Ответы посчитаны отдельно. Подсчёт не заменяет содержательный аудит.")
    print()
    for story in registry.available_stories(PracticeMode.FULL):
        conditions = defaultdict(set)
        signatures = defaultdict(set)
        solutions = defaultdict(set)
        answers = defaultdict(Counter)
        bundles = set()
        for seed in range(SAMPLES):
            snapshot = build_practice_plan(
                PracticeRequest(PracticeMode.FULL, seed, story), registry
            ).snapshot
            bundles.add(tuple(question_signature(snapshot, q) for q in snapshot.questions))
            for q in snapshot.questions:
                conditions[q.family_id].add(q.condition)
                signatures[q.family_id].add(question_signature(snapshot, q))
                solutions[q.family_id].add(q.solution_steps)
                answers[q.family_id][q.canonical_answer] += 1
        print(f"## {story}. Наблюдаемых пятёрок: {len(bundles)}")
        print()
        print("| Семейство | Выдач | Условий | Сигнатур | Ответов | Частота лидера | Разборов |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for family in sorted(signatures):
            print(
                f"| {family} | {sum(answers[family].values())} | {len(conditions[family])} | "
                f"{len(signatures[family])} | {len(answers[family])} | "
                f"{max(answers[family].values())} | {len(solutions[family])} |"
            )
        print()


if __name__ == "__main__":
    main()
