"""Build the self-contained, offline review gallery from actual learner material."""

import base64
import io
import json
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.diagram_layout import mobile_diagram
from app.bot.family_display import template_format, typeset_family_text
from app.bot.math_image import render_math_image
from app.bot.mixed_training import _render_image
from app.bot.part2 import solution_text, statement_text
from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.bot.task_view import question_text, system_rows
from app.math.oge18_render import polygon_construction
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.mobile_photos import scenario_photos_for_question
from app.persistence.part2_bank import ATLAS, figure
from app.persistence.training_insights import family_name
from scripts.oge_bank_quality_audit import _oracle, _ordinary_generator


def examples():
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
                        q.position,
                        q.family_id,
                        f"{story} · seed {seed}",
                        q.family_id,
                        snap.shared_context + "\n\n" + q.condition,
                        q.hints,
                        q.solution_steps,
                        str(q.canonical_answer),
                        scenario_photos_for_question(snap, q.position),
                        (),
                        None,
                    )
            if not remaining:
                break
        if remaining:
            raise ValueError(remaining)
    for number in range(6, 20):
        families, build = _ordinary_generator(number)
        for family in families:
            seed = 2027
            if family in {"OGE06-F001-SUB", "OGE06-F009-PRESCRIBED-NUMERATOR", "OGE08-R05"}:
                from app.math.oge8_scheduler import build_task8_candidate_batch
                from app.math.scheduler import build_candidate_batch

                batch = build_candidate_batch if number == 6 else build_task8_candidate_batch
                seed = batch({"family_queue": [family]}, seed)[0]["seed"]
            q = build(family, seed)
            if not _oracle(number, family, q):
                raise ValueError((number, family))
            data = q.to_snapshot()
            photo = _render_image(number, data)
            if photo:
                photo = mobile_diagram(photo, data)
            solution_photo = ()
            if family in {"OGE18-A06", "OGE18-A07", "OGE18-C01"}:
                solution_photo = (polygon_construction(family, data["points"]),)
            yield (
                number,
                family,
                f"seed {data['seed']} · проверка ответа пройдена",
                data,
                question_text(number, data),
                data["hints"],
                data["solution"],
                str(data["correct_answer"]),
                [photo] if photo else [],
                solution_photo,
                system_rows(number, data),
            )
    seen = set()
    for card in map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()):
        family = card["subtype_id"]
        if family in seen:
            continue
        seen.add(family)
        visuals = card["visuals"]
        yield (
            card["number"],
            family,
            f"Карточка {card['task_id']} · v{card['content_version']}",
            card,
            statement_text(card),
            card["hints"],
            solution_text(card),
            card["answer_or_claim"],
            [figure(v["path"]) for v in visuals if v["role"] == "condition"],
            [figure(v["path"]) for v in visuals if v["role"] == "solution"],
            None,
        )


def picture(png, alt):
    with Image.open(io.BytesIO(png)) as image:
        width = min(540, image.width)
        small = image.resize(
            (width, round(width * image.height / image.width)), Image.Resampling.LANCZOS
        )
        out = io.BytesIO()
        small.save(out, "WEBP", quality=85, method=3)
    data = base64.b64encode(out.getvalue()).decode()
    return (
        f'<img loading="lazy" alt="{escape(alt, quote=True)}" src="data:image/webp;base64,{data}">'
    )


def mobile_witnesses(dst):
    """Keep examples small enough to inspect at their target logical width."""

    def thumb(png, width):
        with Image.open(io.BytesIO(png)) as image:
            return image.resize(
                (width, round(image.height * width / image.width)), Image.Resampling.LANCZOS
            )

    for width in (360, 390, 430):
        groups = []
        for n, f, seed in [
            (7, "OGE07-N01", 3),
            (11, "OGE11-F08", 14),
            (12, "OGE12-R004", 3),
            (13, "OGE13-S01", 2701),
            (16, "OGE16-C06", 4),
            (18, "OGE18-A06", 2027),
            (18, "OGE18-A07", 42),
            (18, "OGE18-C01", 7),
        ]:
            q = _ordinary_generator(n)[1](f, seed).to_snapshot()
            img = _render_image(n, q)
            scene = mobile_diagram(img, q) if img else None
            if n == 18:
                scene = polygon_construction(f, tuple(tuple(p) for p in q["points"]))
            if n == 12:
                txt = "Разбор:\nВыразим C: C = (F − 32) · 5/9."
            elif n in (16, 18):
                txt = "Разбор:\n" + "\n".join(q["solution"])
            else:
                txt = q["condition"]
            rows = system_rows(n, q)
            img = render_math_image(
                typeset_family_text(txt, q),
                scene,
                tuple(typeset_family_text(r, q) for r in rows) if rows else None,
            )
            groups.append(thumb(img, width))
        h = max(x.height for x in groups)
        out = Image.new("RGB", (4 * width, 2 * (h + 30)), "#eee")
        d = ImageDraw.Draw(out)
        for i, im in enumerate(groups):
            x, y = i % 4 * width, i // 4 * (h + 30)
            d.text((x + 8, y + 3), str((7, 11, 12, 13, 16, 18, 18, 18)[i]), fill="black")
            out.paste(im, (x, y + 22))
        out.save(dst / f"mobile-{width}.png")


def main():
    pages = {}
    for (
        n,
        family,
        ref,
        source,
        condition,
        hints,
        steps,
        answer,
        diagrams,
        extras,
        rows,
    ) in examples():

        def panel(value, title, system=None, source=source):
            text = typeset_family_text(value, source)
            return picture(render_math_image(text, None, system), title) if text.strip() else ""

        solution = steps if isinstance(steps, str) else "\n".join(steps)
        name = family_name(family)
        if name == "Тип из прежней версии":
            name = family
        title = escape(name)
        pages.setdefault(n, []).append(
            f'<article id="{escape(family)}"><h3>{title}</h3><small>{escape(family)} · '
            f"{escape(ref)} · {template_format(family)}</small>"
            + panel(condition, "Условие", rows)
            + "".join(picture(d, "Исходный рисунок") for d in diagrams)
            + "<details><summary>Подсказки</summary>"
            + "".join(panel(h, f"Подсказка {i}") for i, h in enumerate(hints, 1))
            + "</details><details><summary>Разбор и ответ</summary>"
            + "".join(picture(d, "Построение в решении") for d in extras)
            + panel(solution + "\nОтвет: " + answer, "Разбор и ответ")
            + "</details></article>"
        )
    out = Path("reports/previews/independent-acceptance")
    out.mkdir(parents=True, exist_ok=True)
    style = """<meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<style>body{margin:auto;padding:1rem;max-width:44rem;background:#f4f5f3;color:#192b31;
font:1rem/1.5 system-ui}article,nav{background:white;padding:1rem;margin:1rem 0}small{display:block;
overflow-wrap:anywhere;color:#47575c}img{display:block;max-width:100%;height:auto;margin:.5rem auto}
summary,a{color:#165955}summary{padding:.7rem 0;cursor:pointer}h3{margin:0}
nav a{display:inline-block;padding:.4rem}</style>"""
    links = "".join(f'<a href="#n{i}">№{i}</a>' for i in sorted(pages))
    html = (
        style
        + "<title>ОГЭ · галерея заданий</title><h1>Задания №1–25</h1>"
        + (
            "<p>Примеры из действующих семейств. Иллюстрации и локальный математический "
            "рендер доступны без сети. Нативный Rich на iPhone проверяется отдельно.</p><nav>"
            + links
            + "</nav>"
        )
    )
    for n in sorted(pages):
        html += f'<section id="n{n}"><h2>Задание №{n}</h2>' + "".join(pages[n]) + "</section>"
    mobile_witnesses(out)
    (out / "index.html").write_text(html, encoding="utf-8")
    print({n: len(p) for n, p in sorted(pages.items())})


if __name__ == "__main__":
    main()
