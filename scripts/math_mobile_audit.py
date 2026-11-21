"""Inspect the shipped presentation spans and render mobile PNG witnesses offline."""

import io
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops

from app.bot.diagram_layout import mobile_diagram
from app.bot.explicit_math import plain_text
from app.bot.family_display import template_format, typeset_family_text
from app.bot.math_image import _explicit_formula, _formula, render_math_image
from app.bot.math_notation import math_spans
from app.bot.mixed_training import _render_image
from app.bot.part2 import solution_text, statement_text
from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.bot.task_view import question_text, system_rows
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.persistence.part2_bank import ATLAS, figure
from scripts.oge_bank_quality_audit import _ordinary_generator

WITNESS = r"""Сравнения и принадлежность
\(a\ne x\), \(x\le y\), \(y\ge a\), \(x\in A\), \(x\notin B\).
\(x_{1,2}=\frac{-b\pm\sqrt{b^2-4ac}}{2a}\)
Углы \(\alpha\), \(\beta\), \(\gamma\). Прямые \(AB\perp CD\).
\(y=\begin{cases}\frac{x+1}{2},&x\le 0\\|x-2|,&x>0\end{cases}\)
\(x\in(-\infty;-1]\cup[3;+\infty)\)"""


def mobile(width, source=WITNESS, diagram=None):
    with Image.open(io.BytesIO(render_math_image(source, diagram))) as image:
        return image.resize(
            (width, round(image.height * width / image.width)), Image.Resampling.LANCZOS
        )


def previews(dest):
    example = next(
        c
        for c in map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines())
        if c["source_id"] == "315053"
    )
    drawing = next(v for v in example["visuals"] if v["role"] == "condition")
    family_dir = dest.parent / "family-contracts"
    family_dir.mkdir(exist_ok=True)
    family_text = "\n\n".join(typeset_family_text(text, family) for family, text in [
        ("OGE06-F006-MIXED-MINUS-DECIMAL", "Вычислите: 11 1/2 − 9,3."),
        ("OGE16-D04", "R = 48√2/(2 · sin 45°)"),
        ("OGE15-F15", "sin B = AC / AB = 3 / 5."),
        ("OGE09-K3", "x₁,₂ = (−(8) ± 4)/(2·2) = −3 и −1"),
        ("OGE11-F05", "1) y=1/2x+0"),
        ("OGE24-common-tangent-ratio", "O₂T₂/ O₁T₁ = PO₂/PO₁ = r₂/r₁"),
        ("OGE13-L01", r"\(a\ne b\), \(a\in A\), \(x\le 3\)"),
    ])
    for width in (360, 390, 430):
        mobile(width, family_text).save(family_dir / f"fractions-{width}.png")
        mobile(width).save(dest / f"formulas-{width}.png")
        mobile(width, statement_text(example), figure(drawing["path"])).save(
            dest / f"geometry-{width}.png"
        )


def fields():
    for story, families in PUBLIC_FAMILIES.items():
        remaining = set(families)
        for seed in range(2027, 2527):
            snap = build_practice_plan(
                PracticeRequest(PracticeMode.FULL, seed, story), public_registry()
            ).snapshot
            for q in snap.questions:
                if q.family_id in remaining:
                    remaining.remove(q.family_id)
                    yield (
                        "stories",
                        q.family_id,
                        {},
                        None,
                        [
                            snap.shared_context,
                            q.condition,
                            *q.hints,
                            *q.solution_steps,
                            str(q.canonical_answer),
                        ],
                    )
            if not remaining:
                break
        if remaining:
            raise ValueError(remaining)
    for number in range(6, 20):
        families, build = _ordinary_generator(number)
        for family in families:
            q = build(family, 2027).to_snapshot()
            photo = _render_image(number, q)
            steps = q["solution"]
            yield (
                "ordinary",
                q,
                {0: mobile_diagram(photo, q) if photo else None},
                system_rows(number, q),
                [
                    question_text(number, q),
                    *q["hints"],
                    *(steps if isinstance(steps, list) else [steps]),
                    str(q["correct_answer"]),
                ],
            )
    for card in map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()):
        yield (
            "written",
            card,
            {
                0 if v["role"] == "condition" else len(card["hints"]) + 1: figure(v["path"])
                for v in card["visuals"]
            },
            None,
            [statement_text(card), *card["hints"], solution_text(card), card["answer_or_claim"]],
        )


def main():
    counts = Counter()
    min_gutter = {360: 360, 390: 390, 430: 430}
    tallest = 0
    for origin, identity, drawings, rows, texts in fields():
        counts[origin] += 1
        template = template_format(identity)
        if template is None:
            raise ValueError(("unregistered template", identity))
        for index, text in enumerate(texts):
            text = typeset_family_text(text, identity)
            spans = [s for s in math_spans(text) if s.latex]
            counts[template] += 1
            for span in spans:
                image = _explicit_formula(span.latex) if span.explicit else _formula(span.latex)
                if image.getbbox() is None:
                    raise ValueError((origin, span.source))
            if template == "png" or spans or drawings.get(index):
                rendered_rows = (tuple(typeset_family_text(row, identity) for row in rows)
                                 if index == 0 and rows else None)
                png = render_math_image(text, drawings.get(index), rendered_rows)
                with Image.open(io.BytesIO(png)) as scene:
                    tallest = max(tallest, scene.height)
                    for width in min_gutter:
                        preview = scene.resize(
                            (width, round(scene.height * width / scene.width)),
                            Image.Resampling.LANCZOS,
                        ).convert("L")
                        ink = ImageChops.invert(preview).point(
                            lambda level: 255 if level > 48 else 0
                        )
                        bounds = ink.getbbox()
                        if bounds is None:
                            raise ValueError(("empty raster", identity, index))
                        left, top, right, bottom = bounds
                        gutter = min(left, top, width - right, preview.height - bottom)
                        if gutter < 3:
                            raise ValueError(
                                ("insufficient clearance", identity, index, width, gutter)
                            )
                        min_gutter[width] = min(min_gutter[width], gutter)
                counts["raster_scenes"] += 1
            if any(delimiter in plain_text(text) for delimiter in (r"\(", r"\[", r"\frac")):
                raise ValueError(text)
    counts.update({f"minimum_margin_at_{w}px": gap for w, gap in min_gutter.items()})
    counts["maximum_scene_height_px"] = tallest
    dest = Path("reports/previews/math-mobile")
    dest.mkdir(parents=True, exist_ok=True)
    previews(dest)
    (dest / "coverage.json").write_text(json.dumps(dict(counts), indent=2) + "\n")
    print(counts)


if __name__ == "__main__":
    main()
