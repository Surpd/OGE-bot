"""Independent sequence model for comparison with PostgreSQL issuance."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from app.persistence.part2_bank import ATLAS


def sequence(cards, catalog, number, requests, owner=1, *, previous=False):
    profiles = {
        task: (g["id"], g["additional_step"], g["method"])
        for groups in catalog.values()
        for g in groups
        for task in g["cards"]
    }
    seen = set()
    subtype_age, group_age, family_age, level_age = {}, {}, {}, {}
    method_age = {}
    recent = None
    sequence_ids = []
    for turn, subtype in enumerate(requests):
        choices = [
            c
            for c in cards
            if c["number"] == number
            and (not subtype or c["subtype_id"] == subtype)
            and c["task_id"] not in seen
        ]
        if previous:
            choices = [c for c in choices if not c["task_id"].endswith("-extension")]
        if not choices:
            break

        counts = Counter(profiles[c["task_id"]][0] for c in choices)
        majority = next((key for key, n in counts.items() if 2 * n > len(choices)), None)
        if subtype is None:
            majority = None

        def rank(c, last=recent, dominant=majority):
            task = c["task_id"]
            group, extra, method = profiles[task]
            tie = hashlib.md5(f"{task}{owner}".encode(), usedforsecurity=False).hexdigest()
            sub = subtype_age.get(c["subtype_id"], -1)
            if previous:
                return sub, tie, task
            return (
                group == last,
                sub,
                dominant is not None and group != dominant,
                group_age.get(group, -1),
                family_age.get(c["family_id"], -1),
                method_age.get(method, -1),
                level_age.get(extra, -1),
                tie,
                task,
            )

        card = min(choices, key=rank)
        tid = card["task_id"]
        recent, extra, method = profiles[tid]
        subtype_age[card["subtype_id"]] = group_age[recent] = turn
        family_age[card["family_id"]] = level_age[extra] = turn
        method_age[method] = turn
        seen.add(tid)
        sequence_ids.append(tid)
    return sequence_ids


def report():
    catalog = json.loads((ATLAS / "rotation.json").read_text())
    cards = list(map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()))
    types = json.loads((ATLAS / "taxonomy.json").read_text())["subtypes"]
    sources = {c["task_id"]: c["source_id"] for c in cards}
    out = [
        "# Учебные последовательности №20–25",
        "",
        "[Какие постановки добавить по каждому подтипу](part2-rotation-gaps.md)",
        "",
        "Модель для ученика без истории (условный ID 1). Цифры соответствуют конструкциям "
        "в легенде строки. Перестановка числовых данных сама по себе группу не меняет.",
        "",
    ]
    for t in types:
        s = t["subtype_id"]
        groups = catalog[s]
        out.extend([f"## {s} · {t['title']}", "", t["key_method"], ""])
        labels = {}
        for i, group in enumerate(groups, 1):
            for tid in group["cards"]:
                labels[tid] = str(i)
            level = "с дополнительным шагом" if group["additional_step"] else "обычная цепочка"
            out.append(
                f"{i}. {group['construction']} ({len(group['cards'])} шт., {level}). "
                f"Метод — {group['method']}."
            )
        previous_labels = labels.copy()
        for i, group in enumerate(groups, 1):
            for pinned in group.get("historical_versions", []):
                previous_labels[pinned.split("@")[0]] = str(i)
        for previous, name in [(True, "Раньше"), (False, "Теперь")]:
            seq = sequence(
                cards,
                catalog,
                t["number"],
                [s] * (6 if previous else len(labels)),
                previous=previous,
            )
            out.extend(
                [
                    "",
                    name
                    + " — "
                    + " → ".join((previous_labels if previous else labels)[id] for id in seq)
                    + " ("
                    + ", ".join(sources[id] for id in seq)
                    + ").",
                ]
            )
        out.append("")
    out.extend(
        [
            "## Подтипы с преобладанием одного шаблона",
            "",
            ", ".join(
                s for s, groups in catalog.items() if max(len(g["cards"]) for g in groups) >= 5
            ),
            "",
            "В каждом из этих наборов пять или шесть карточек принадлежат одной группе. "
            "После исчерпания альтернатив возвращается знакомый шаблон. Для расширения нужны "
            "новые условия и проверенные решения в границах подтипа.",
            "",
        ]
    )
    for n in range(20, 26):
        seq = sequence(cards, catalog, n, [None] * 15)
        out.extend([f"**№{n}, свободный выбор** — " + " → ".join(sources[i] for i in seq), ""])
    Path("reports/part2-rotation.md").write_text("\n".join(out))


if __name__ == "__main__":
    report()
