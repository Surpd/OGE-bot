"""Refresh GitHub examples with uv run python -m scripts.atlas_first_part."""

from __future__ import annotations

import hashlib
import json
from itertools import groupby
from pathlib import Path

from app.bot.mixed_training import _render_image
from app.bot.scenario_training import PUBLIC_FAMILIES, STORY_NAMES, public_registry
from app.bot.task_view import question_text
from app.bot.trainings import TRAININGS
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.mobile_photos import scenario_photos_for_question
from app.persistence.training_insights import family_name
from scripts.oge_bank_quality_audit import _oracle, _ordinary_generator

OUT = Path(__file__).resolve().parents[1] / "atlas/first"
SEED = 2027
SEVEN = {
    "OGE07-C01": "Отрезок, содержащий дробь",
    "OGE07-C02": "Между какими целыми лежит корень",
    "OGE07-C03": "Какой корень принадлежит отрезку",
    "OGE07-C04": "Какая дробь принадлежит отрезку",
    "OGE07-C06": "Между какими целыми лежит дробь",
    "OGE07-N01": "Какая точка изображает заданный корень",
    "OGE07-N04": "Какой корень изображён точкой A",
}


STORY_TITLES = {
    "TYRES-TABLE-EXTREME": "Допустимый размер по таблице",
    "TYRES-SIDEWALL": "Высота боковины",
    "TYRES-DIAMETER": "Диаметр колеса",
    "TYRES-RADIUS-DELTA": "Разность радиусов",
    "TYRES-PERCENT-ROTATION": "Изменение пробега за оборот",
    "PAPER-F01": "Формат по размерам листа",
    "PAPER-F02": "Количество листов после разрезания",
    "PAPER-F03": "Ширина листа",
    "PAPER-F04": "Отношение сторон",
    "PAPER-F06": "Диагональ и меньшая сторона",
    "PAPER-F07": "Масштабирование шрифта",
    "TARIFF-F01-MONTHS-MINUTES": "Месяцы по расходу минут",
    "TARIFF-F04-MONTHLY-BILL": "Плата за месяц",
    "TARIFF-F05-EXTREMUM": "Экстремум расхода по графику",
    "TARIFF-F09-PERCENT-FEE": "Изменение абонентской платы",
    "TARIFF-F12-HOME-ISP": "Выбор тарифа домашнего интернета",
    "GARDEN-01-IDENTIFY": "Объекты на плане участка",
    "GARDEN-02-TILES-PACKS": "Пачки плитки",
    "GARDEN-04-PERIMETER-POLYGON": "Периметр дома",
    "GARDEN-07-PERCENT-BUILDINGS": "Доля площади под постройками",
    "GARDEN-09-HEAT-BREAKEVEN": "Окупаемость отопления",
    "FLAT-01-ROOM-MATCH": "Комнаты на плане",
    "FLAT-02-PARQUET-PACK": "Упаковки паркета",
    "FLAT-02-TILE-PACK": "Упаковки плитки",
    "FLAT-03-RECT-AREA": "Площадь помещения",
    "FLAT-04-RECT-PERCENT": "Сравнение площадей в процентах",
    "FLAT-05-INTERNET-MIN": "Стоимость интернета",
    "FLAT-05-WASHER-MIN": "Стоимость стиральной машины",
    "STOVE-F01-CAPACITY-LIMITS": "Допустимый объём парной",
    "STOVE-F02-ATTRIBUTE-MATCH": "Печи по характеристикам",
    "STOVE-F03-VOLUME": "Объём парной",
    "STOVE-F04-FLOOR-AREA": "Площадь пола",
    "STOVE-F05-WALL-AREA-NET": "Площадь стен с учётом проёмов",
    "STOVE-F06-PURCHASE-EXTRA-COSTS": "Покупка с дополнительными расходами",
    "STOVE-F07-FIT-WOOD-DELIVERY": "Подбор и доставка дровяной печи",
    "STOVE-F08-COST-COMPARISON": "Сравнение стоимости",
    "STOVE-F09-DIRECT-DISCOUNT": "Цена после скидки",
    "STOVE-F10-REVERSE-DISCOUNT": "Цена до скидки",
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": "Две скидки",
    "STOVE-F12-ARCH-RADIUS": "Радиус арки",
}

CLAIM_TOPICS = {
    "angles_lines": "Углы и прямые",
    "areas": "Площади",
    "circles": "Окружности",
    "isosceles_triangle": "Равнобедренный треугольник",
    "quadrilaterals": "Четырёхугольники",
    "right_triangle": "Прямоугольный треугольник",
    "tangency": "Касание",
    "trapezoids": "Трапеции",
    "triangle_angles": "Углы треугольника",
    "triangle_centers": "Замечательные точки треугольника",
    "triangle_congruence": "Равенство треугольников",
    "triangle_inequality": "Неравенство треугольника",
    "triangle_similarity": "Подобие треугольников",
}


def material(data, label):
    name = hashlib.sha256(data).hexdigest()[:20] + ".png"
    (OUT / "figures" / name).write_bytes(data)
    return f"![{label}](figures/{name})"


def details(label, body):
    return f"<details>\n<summary>{label}</summary>\n\n{body}\n\n</details>"


def lines(value):
    if isinstance(value, str):
        return value
    return "\n\n".join(f"{i}. {step}" for i, step in enumerate(value, 1))


def teaching(q, answer, solution):
    assert q["hints"] and q[solution] and str(q[answer]).strip()
    return [details(f"Подсказка {i}", hint) for i, hint in enumerate(q["hints"], 1)] + [
        details("Ответ и разбор", f"**Ответ** · {q[answer]}\n\n{lines(q[solution])}")
    ]


def page(name, title, blocks):
    content = [f"# {title}", "[← Атлас №1–25](../README.md)", *blocks]
    (OUT / f"{name}.md").write_text("\n\n".join(content) + "\n", encoding="utf-8")


def ordinary(training):
    n = training.number
    families, build = _ordinary_generator(n)
    blocks = []
    index = []
    arithmetic = {}
    if n == 6:
        structures = json.loads((OUT.parent / "oge6_reference_structures.json").read_text())
        arithmetic = {r["id"]: r["label"] for r in structures["structures"]}
    for family in families:
        instance = build(family, SEED)
        assert _oracle(n, family, instance), family
        q = instance.to_snapshot()
        assert family == q["family_id"]
        name = (
            arithmetic[q["reference_structure_id"]]
            if n == 6
            else SEVEN.get(family, family_name(family))
        )
        index.append(f"- [{name}](#{family.lower()}) · `{family}`")
        blocks.extend(
            [
                f'<a id="{family.lower()}"></a>\n\n## {name}',
                question_text(n, q).replace("\n", "<br>\n"),
            ]
        )
        image = _render_image(n, q)
        if image:
            blocks.append(material(image, f"Материал задания №{n} · {name}"))
        blocks.extend(teaching(q, "correct_answer", "solution"))
        blocks.append(f"`{family}` · seed `{q['seed']}` · версия `{q['generator_version']}`")
    ref = next((OUT.parent).glob(f"oge{n:02d}_reference_structures.json"), None)
    ref = ref or OUT.parent / f"oge{n}_reference_structures.json"
    assert ref.is_file()
    if n == 19:
        blocks.insert(0, "[Все утверждения банка с объяснениями](claims.md)")
    page(
        n,
        f"№{n} · {training.title}",
        [
            f"{len(families)} семейств или режимов в выдаче. "
            f"[Источники и структуры](../{ref.name}).",
            "\n".join(index),
            *blocks,
        ],
    )


def story_context(context):
    sections = []
    for is_table, group in groupby(context.splitlines(), lambda line: "|" in line):
        rows = list(group)
        if is_table:
            if len(rows) > 1 and "---" not in rows[1]:
                columns = len(rows[0].strip("|").split("|"))
                rows.insert(1, "|".join("---" for _ in range(columns)))
            sections.append("\n".join(rows))
        else:
            sections.append("<br>\n".join(rows).strip())
    return "\n\n".join(sections)


def story_examples(story):
    registry = public_registry()
    remaining = set(PUBLIC_FAMILIES[story])
    index, blocks = [], []
    for seed in range(SEED, SEED + 500):
        snapshot = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, story), registry
        ).snapshot
        questions = snapshot.questions
        new = remaining.intersection(q.family_id for q in questions)
        if not new:
            continue
        blocks.extend([f"## Комплект {seed}", story_context(snapshot.shared_context)])
        for q in questions:
            anchor = f"{seed}-{q.position}"
            if q.family_id in new:
                index.append((q.position, q.family_id, anchor))
            blocks.append(f'<a id="q-{anchor}"></a>\n\n### №{q.position} · `{q.family_id}`')
            blocks.append(q.condition)
            for data in scenario_photos_for_question(
                snapshot, q.position, previous_position=q.position - 1 if q.position > 1 else None
            ):
                blocks.append(material(data, f"{STORY_NAMES[story]} · материал к №{q.position}"))
            blocks.extend(teaching(q.to_snapshot(), "canonical_answer", "solution_steps"))
        remaining -= new
        if not remaining:
            break
    if remaining:
        raise ValueError(f"Missing public examples for {remaining}")
    items = [
        f"- №{n} · [{STORY_TITLES[family]}](#q-{anchor}) · `{family}`"
        for n, family, anchor in sorted(index)
    ]
    page(
        story.lower(),
        STORY_NAMES[story],
        [
            "Каждая пятёрка использует общий набор данных. Рисунок остаётся у первого вопроса, "
            "в котором он нужен; при смене материала следующий рисунок показан рядом с вопросом.",
            "\n".join(items),
            *blocks,
        ],
    )


def main():
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    bank = json.loads((OUT.parents[1] / "app/math/oge19_bank.json").read_text())
    blocks = []
    for topic, items in groupby(
        sorted(bank["items"], key=lambda i: i["topic"]), lambda i: i["topic"]
    ):
        blocks.append("## " + CLAIM_TOPICS[topic])
        for item in items:
            verdict = "Верно" if item["is_true"] else "Неверно"
            source = item["source"]
            blocks.extend(
                [
                    f"**{item['id']}** · {item['statement']}",
                    details(
                        "Проверить",
                        f"**{verdict}.** {item['explanation']} "
                        f"[Источник {source['task_id']}]({source['url']})",
                    ),
                ]
            )
    page("claims", "№19 · Банк утверждений", blocks)
    for t in TRAININGS:
        ordinary(t)
    for story in sorted(PUBLIC_FAMILIES):
        story_examples(story)


if __name__ == "__main__":
    main()
