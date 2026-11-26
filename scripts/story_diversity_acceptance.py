"""Measure exact-family inputs via the issuance oracle, and publish comparable examples."""
from __future__ import annotations

import csv
import html
import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.math.scenario_engine import (
    FamilyQuestionBuilder,
    FamilyScenarioGenerator,
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
)
from app.math.scenarios.mobile_photos import scenario_photos_for_question
from app.math.scenarios.recent_questions import question_signature

OUT = Path("reports/story-diversity")
BASELINE = Path("reports/live-training-acceptance/audit.csv")
PARAMETERS = {
    "FLAT-02-TILE-PACK": "bathroom dimensions, tile size and tiles per pack",
    "FLAT-02-PARQUET-PACK": "living room dimensions, board dimensions and boards per pack",
    "FLAT-03-RECT-AREA": "smaller loggia dimensions and cell scale",
    "FLAT-04-RECT-PERCENT": "pantry and bathroom dimensions; pantry is the comparison base",
    "FLAT-05-WASHER-MIN": "price, installation and delivery of eligible offers",
    "FLAT-05-INTERNET-MIN": "traffic, fees, included traffic and overage rates",
    "GARDEN-02-TILES-PACKS": "paved paths, pad dimensions and pack capacity",
    "GARDEN-04-PERIMETER-POLYGON": "house boundary and grid scale",
    "GARDEN-07-PERCENT-BUILDINGS": "areas of four buildings and entire plot",
    "PAPER-F02": "initial sheet count and number of halvings",
    "PAPER-F03": "measured side in millimetres and rounding multiple",
    "PAPER-F04": "short/long ISO dimensions and rounding precision",
    "PAPER-F06": "dimensions for reconstructing the diagonal and reference side",
    "PAPER-F07": "initial font size and corresponding side lengths",
    "TARIFF-F04-MONTHLY-BILL": "monthly fee, usage, included allowances and overage charges",
    "TARIFF-F09-PERCENT-FEE": "old and increased subscription fee",
}


def example(scene, q):
    images = []
    for data in scenario_photos_for_question(scene, q.position):
        path = Path("assets") / (sha256(data).hexdigest() + ".png")
        (OUT / path).write_bytes(data)
        images.append(f'<a href="{path.as_posix()}"><img src="{path.as_posix()}"'
                      ' alt="Данные задачи"></a>')
    esc = html.escape
    def steps(items):
        return "<ol>" + "".join(f"<li>{esc(s)}</li>" for s in items) + "</ol>"
    return (f"<article><small>seed {scene.seed} · {esc(scene.generator_version)}</small>"
            f"<p>{esc(scene.shared_context)}</p>{''.join(images)}<h3>{esc(q.condition)}</h3>"
            f"<details><summary>Подсказки</summary>{steps(q.hints)}</details>"
            f"<h4>Разбор</h4>{steps(q.solution_steps)}<b>Ответ {esc(q.canonical_answer)}</b>"
            f"<details><summary>Математические входы</summary><code>"
            f"{esc(question_signature(scene, q)[2])}</code></details></article>")


def measure_story(registry, story, baseline):
    adapter = registry.adapter(story)
    generator, builder = adapter.generator, adapter.question_builder
    oracle = adapter.independent_oracle
    results = {row["family"]: (set(), set(), []) for row in baseline}
    for seed in range(100):
        # Several families use precisely the same world. Validate/render it once
        # per seed, retaining no images between seeds.
        worlds = []
        for row in baseline:
            family, position = row["family"], int(row["position"])
            draft = (generator.generate_scenario_for_family(seed, position, family)
                     if isinstance(generator, FamilyScenarioGenerator)
                     else generator.generate_scenario(seed))
            rendered = next((r for d, r in worlds if d == draft), None)
            if rendered is None:
                oracle.validate_scenario(draft)
                rendered = adapter.renderer.render_scenario(draft)
                worlds.append((draft, rendered))
            q = (builder.build_question_for_family(draft, position, family)
                 if isinstance(builder, FamilyQuestionBuilder)
                 else builder.build_question(draft, position))
            assert q.family_id == family and q.scenario_seed == seed
            oracle.validate_question(draft, q, rendered)
            sig = question_signature(draft, q)
            distinct, answers, examples = results[family]
            if family in PARAMETERS and len(examples) < 3 and sig not in distinct:
                scene = build_practice_plan(
                    PracticeRequest(PracticeMode.SINGLE, seed, story, position, family), registry,
                ).snapshot
                assert all(x.scenario_seed == seed for x in scene.questions)
                examples.append(example(scene, scene.questions[position - 1]))
            distinct.add(sig)
            answers.add(q.canonical_answer)
    return results


def main():
    (OUT / "assets").mkdir(exist_ok=True, parents=True)
    registry = public_registry()
    rows, sections = [], []
    with BASELINE.open(encoding="utf-8", newline="") as stream:
        baseline = list(csv.DictReader(stream))
    assert {r["family"] for r in baseline} == set().union(*PUBLIC_FAMILIES.values())
    for story in dict.fromkeys(row["story"] for row in baseline):
        story_rows = [row for row in baseline if row["story"] == story]
        results = measure_story(registry, story, story_rows)
        for row in story_rows:
            family = row["family"]
            distinct, answers, examples = results[family]
            numeric = {Decimal(answer.replace(",", ".")) for answer in answers}
            rows.append(dict(family=family, before=row["distinct_in_100_seeds"],
                             after=len(distinct), different_answers=len(numeric),
                             answer_strings=len(answers),
                             parameters=PARAMETERS.get(family, row["mathematical_inputs"])))
            if examples:
                cards = "".join(examples)
                sections.append(f'<section><h2>{family}</h2><div>{cards}</div></section>')
        print(story, flush=True)
    with (OUT / "matrix.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "index.html").write_text(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>Математические варианты №1–5</title>'
        '<style>body{font:16px/1.5 system-ui;margin:2vw;color:#142837}section div{display:grid;'
        'grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:1rem}'
        'article{padding:1rem;background:#f3f6f8;overflow-wrap:anywhere}img{max-width:100%}'
        'p,h3{white-space:pre-line}h3{font-size:1.05rem}code{white-space:pre-wrap}</style>'
        '<h1>ОГЭ №1–5 · варианты одного семейства</h1>'
        '<a href="matrix.csv">Матрица 40 семейств</a> · '
        '<a href="telegram/index.html">Отправки Telegram</a>'
        + "".join(sections) + "</html>\n", encoding="utf-8",
    )
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
