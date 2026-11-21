"""Summarize real first-part selections and the PostgreSQL-tested written selection model."""

import json
import statistics
import time
from collections import Counter
from itertools import groupby
from pathlib import Path

from app.bot.scenario_training import public_registry
from app.math.first_rotation import topics
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.recent_questions import rotated_plan
from app.persistence.part2_bank import ATLAS
from scripts.part2_rotation_audit import sequence

REPORT = Path("reports")


def run_length(items):
    return max((sum(1 for _ in group) for _, group in groupby(items)), default=0)


def practical():
    registry = public_registry()
    lines = [
        "## №1–5 · один сюжет на комплект",
        "",
        "Одинаковые seed 0–17, случайный выбор. Слева исходный выбор сюжета по seed "
        "в Mix, справа выбор с историей. SINGLE показан для сравнения алгоритмов выбора.",
        "",
    ]
    for mode in (PracticeMode.FULL, PracticeMode.SINGLE):
        for rotated in (False, True):
            history, stories = [], []
            elapsed = []
            for seed in range(18):
                request = PracticeRequest(mode, seed)
                start = time.perf_counter()
                plan = (
                    rotated_plan(request, registry, history)
                    if rotated
                    else build_practice_plan(request, registry)
                )
                elapsed.append(1000 * (time.perf_counter() - start))
                questions = [plan.snapshot.questions[pos - 1] for pos in plan.selected_positions]
                assert all(q.scenario_seed == plan.snapshot.seed for q in questions)
                history = [*(q.family_id for q in questions), *history][:30]
                stories.append(plan.snapshot.story_code)
            label = "с историей" if rotated else "по seed"
            lines.extend(
                [
                    f"**{mode.value}, {label}** · "
                    + " → ".join(stories)
                    + f". Медиана {statistics.median(elapsed):.1f} мс.",
                    "",
                ]
            )
    lines.extend(["| Сюжет | №1 | №2 | №3 | №4 | №5 |", "|---|---|---|---|---|---|"])
    for story in registry.story_codes:
        entries = registry.adapter(story).family_registry
        cells = [
            ", ".join(f.family_id for f in entries if f.position == p and f.available) or "закрыто"
            for p in range(1, 6)
        ]
        lines.append("| " + " | ".join([story, *cells]) + " |")
    return lines


def main():
    lines = [
        "# Ротация ОГЭ №1–25",
        "",
        "База сравнения первой части — 1ac9a07. В обеих сериях по 100 запросов реальному "
        "построителю кандидатов Mix для каждого №6–19, состояние очереди переносится после "
        "каждой выдачи. Время — медиана построения пачки, без SQL и доставки Telegram. "
        "В повтор попадает совпадение fingerprint в любом месте серии, включая возврат "
        "после окна защиты. Серия моделирует одного ученика по одному номеру.",
        "",
        "| № | Семейств до → после | Тем после | Макс. серия одной темы до → после "
        "| Повтор fingerprint до → после | Медиана мс до → после |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    before, after = (
        json.loads((REPORT / f"first-rotation-{x}.json").read_text()) for x in ["before", "after"]
    )
    details = []
    for n, row in after.items():
        old = before[n]
        assert old["issued"] == row["issued"] == 100
        a, b = ([topics()[family] for family in r["sequence"]] for r in (old, row))
        lines.append(
            f"| [{n}](../atlas/first/{n}.md) | {len(old['families'])} → "
            f"{len(row['families'])} | {len(set(b))} | {run_length(a)} → "
            f"{run_length(b)} | {old['repeated_fingerprints']} → "
            f"{row['repeated_fingerprints']} | {old['median_ms']} → {row['median_ms']} |"
        )
        details.append(
            f"- **№{n}** · минимум–максимум выдач семейства "
            f"{min(row['families'].values())}–{max(row['families'].values())} из 100. "
            + ", ".join(f"{key} — {count}" for key, count in Counter(b).items())
        )
    lines.extend(
        [
            "",
            "Математические темы объединяют близкие методы. Например, "
            "сравнение корня с границами на рисунке и в тексте относится к одной теме. "
            "Для №19 тема обозначает раздел утверждений. Полный учёт отдельных теорем "
            "ведётся по ID утверждений внутри задания.",
            "",
            *details,
            "",
            "Во второй серии представлены все 163 зарегистрированных семейства и режима. "
            "В первой отсутствовали пять тематических режимов №19. Повторы после исчерпания "
            "короткого пула возможны, особенно в №18. Данные по фиксированным формулам, "
            "интервалам параметров и примерам решения доступны по ссылке у каждого номера.",
            "",
            "[Все выдачи до](first-rotation-before.json) · "
            "[Все выдачи после](first-rotation-after.json) · "
            "[Семейства и темы](../app/math/first_rotation_groups.json).",
            "",
            *practical(),
            "",
            "ROUTE выключен из-за незавершённой визуальной сверки исходной карты. "
            "У фиксированного сюжета и позиции остаются ограничения самого банка. "
            "[Сигнатуры и число вариантов по каждой позиции](OGE15_V2_DIVERSITY.md).",
            "",
            "## Письменные №20–25",
            "",
            "Модель ранжирования для одного ученика, 30 новых карточек подряд. "
            "До — порядок PR #98 на 522 карточках, после — действующий банк. "
            "Время ниже относится только к локальному выбору 30 ID.",
            "",
            "| № | Подтипов | Конструкций всего | Конструкций за 30 до → после "
            "| Повторы ID | Макс. серия группы после | мс за 30 после |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    cards = list(map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()))
    catalog = json.loads((ATLAS / "rotation.json").read_text())
    profiles = {tid: g["id"] for groups in catalog.values() for g in groups for tid in g["cards"]}
    for n in range(20, 26):
        old = sequence(
            [c for c in cards if c["source_id"] != "A20-power-equality-extension"],
            catalog,
            n,
            [None] * 30,
        )
        start = time.perf_counter()
        new = sequence(cards, catalog, n, [None] * 30)
        latency = 1000 * (time.perf_counter() - start)
        active = [c for c in cards if c["number"] == n]
        old_groups, new_groups = ([profiles[tid] for tid in batch] for batch in (old, new))
        assert len(set(new)) == 30
        lines.append(
            f"| {n} | {len({c['subtype_id'] for c in active})} | "
            f"{len({profiles[c['task_id']] for c in active})} | "
            f"{len(set(old_groups))} → {len(set(new_groups))} | 0 | "
            f"{run_length(new_groups)} | {latency:.1f} |"
        )
    lines.extend(
        [
            "",
            "[Порядок для каждого из 81 подтипов и легенда методов](part2-rotation.md) "
            "· [Пробелы банка и предлагаемые варианты](part2-rotation-gaps.md).",
            "",
            "У письменной работы есть черновик, фото и оценка 0–2. "
            "Будущий письменный Mix сможет выбирать номер перед вызовом существующей "
            "выдачи и предлагать возврат к открытой работе. Текущий Mix ограничен №1–19.",
            "",
            "Команды из корня репозитория",
            "",
            "```sh",
            "python -m scripts.first_rotation_audit reports/first-rotation-after.json",
            "python -m scripts.rotation_comparison",
            "```",
            "",
        ]
    )
    (REPORT / "rotation-1-25.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
