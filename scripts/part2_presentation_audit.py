"""Validate every current card and produce mobile-width contact sheets for all subtypes."""

import argparse
import io
import json
import re
from collections import defaultdict
from pathlib import Path

from matplotlib import get_data_path
from PIL import Image, ImageDraw, ImageFont

from app.bot.explicit_math import formulas, plain_text
from app.bot.math_image import _explicit_formula, render_math_image
from app.bot.part2 import solution_text, statement_text
from app.bot.part2_check import grading_reply
from app.bot.presentation import format_math_message, format_rich_message
from app.part2_grading import Assessment
from app.persistence.part2_bank import ATLAS, figure, load_bank

DRAWING_REFERENCE = re.compile(r"(?:на|по) рисун(?:ке|ку)|(?:на|по) данно[мму]+ график", re.I)
RAW_TEX = re.compile(r"\\(?:[a-zA-Z]+|[()\[\]{}])")
ASSET_ROLE = {"condition", "solution"}


FIXED_PROOFS = {
    "A24-cyclic-external-03": "explicit_equal_secant_distances_from_M",
    "A24-cyclic-converse-01": "inscribed_angle_and_common_arc",
    "A24-common-tangent-ratio-05": "correct_correspondence_of_tangent_legs",
    "311573": "restored_internal_feet_from_source_diagram",
    "155": "restored_internal_points_from_source_diagram",
    "A24-cyclic-external-02": "secant_through_center",
    "A24-common-chord-03": "center_at_chord_midpoint",
    "A24-rigid-motion-01": "coincident_points_at_vertex",
}


def font(size: int):
    return ImageFont.truetype(get_data_path() + "/fonts/ttf/DejaVuSans.ttf", size)


def photo(card, role):
    image = next((v for v in card["visuals"] if v["role"] == role), None)
    return figure(image["path"]) if image else None


def panel(text, width, drawing=None):
    with Image.open(io.BytesIO(render_math_image(text, drawing))) as image:
        return image.resize(
            (width, round(width * image.height / image.width)), Image.Resampling.LANCZOS
        )


def preview(number, cards, width, out):
    blocks = []
    for card in cards:
        parts = [
            panel(statement_text(card), width, photo(card, "condition")),
            panel("Подсказка №1:\n\n" + card["hints"][0], width),
            panel(solution_text(card), width, photo(card, "solution")),
        ]
        blocks.append((card["subtype_id"], parts))
    gap = 16
    column_heights = [sum(p.height + 4 for p in parts) + 37 for _, parts in blocks]
    rows = (len(blocks) + 2) // 3
    heights = [max(column_heights[i * 3 : i * 3 + 3]) for i in range(rows)]
    image = Image.new("RGB", (3 * width + 4 * gap, sum(heights) + (rows + 1) * gap + 36), "#e9eef3")
    draw = ImageDraw.Draw(image)
    draw.text(
        (gap, 13), f"ОГЭ №{number} · {width} px · PNG-предпросмотр", font=font(17), fill="#17212b"
    )
    y = gap + 36
    for row in range(rows):
        for index, (label, parts) in enumerate(blocks[row * 3 : row * 3 + 3]):
            x = gap + index * (width + gap)
            draw.text((x + 3, y), label, font=font(13), fill="#17212b")
            dy = y + 23
            for part in parts:
                image.paste(part, (x, dy))
                dy += part.height + 4
        y += heights[row] + gap
    image.save(out / f"oge-{number}-{width}.jpg", quality=84, optimize=True)


def preview_feedback(width, out):
    report = Assessment.model_validate(
        {
            "status": "graded",
            "score": 1,
            "max_score": 2,
            "needs_review": False,
            "confidence": 0.9,
            "correct_steps": [r"Вы верно нашли запрет \(x\ne 4\)."],
            "errors": [r"При \(x=4\) знаменатель обращается в нуль."],
            "criterion_evidence": [
                {
                    "criterion": "График построен верно, но ответ неполный.",
                    "student_evidence": r"Отмечена выколотая точка \((4;-5/4)\).",
                }
            ],
            "feedback": "График построен, но указаны не все значения параметра.",
            "next_step": r"Проверьте отдельно горизонталь \(y=-1\).",
        }
    )
    panels = [
        panel(grading_reply(report, "atlas_training_rubric"), width),
        panel(
            "Письменные работы\n\n1. №22 · Графики функций\n20.11.2026 · 1/2\n\n"
            "2. №24 · Доказательства\n20.11.2026 · Пропущено",
            width,
        ),
    ]
    canvas = Image.new("RGB", (width + 24, sum(p.height for p in panels) + 65), "#e9eef3")
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 9), "Демонстрационные данные", font=font(13), fill="#17212b")
    y = 34
    for p in panels:
        canvas.paste(p, (12, y))
        y += p.height + 12
    canvas.save(out / f"feedback-history-{width}.jpg", quality=84, optimize=True)


def audit(previews, report):
    _, entries = load_bank()
    reviewed = json.loads((ATLAS / "reviewed_versions.json").read_text())
    groups = defaultdict(dict)
    records = []
    for task_id, version, payload, digest in entries:
        card = json.loads(payload)
        number = card["number"]
        subtype = card["subtype_id"]
        # Select the most informative sample. Tie-break on the persisted ID.
        rank = (
            len(card["visuals"]) + bool(photo(card, "condition")),
            len(list(formulas(card["statement"]))),
            len(card["statement"]),
            task_id,
        )
        if subtype not in groups[number] or rank > groups[number][subtype][0]:
            groups[number][subtype] = (rank, card)
        errors = []
        fields = [statement_text(card), solution_text(card), *card["hints"]]
        widths = []
        for field in fields:
            rendered = format_rich_message(field)
            plain = format_math_message(field)
            if RAW_TEX.search(plain) or r"\(" in rendered or r"\[" in rendered:
                errors.append("raw_tex")
            for _, _, latex in formulas(field):
                try:
                    widths.append(_explicit_formula(latex).width)
                except (ValueError, RecursionError):
                    errors.append("mathtext")
            if RAW_TEX.search(plain_text(field)):
                errors.append("unparsed_source")
        asset_refs = []
        if DRAWING_REFERENCE.search(card["statement"]) and not photo(card, "condition"):
            errors.append("missing_condition_asset")
        for visual in card["visuals"]:
            role = visual["role"]
            if (
                role not in ASSET_ROLE
                or number == 22
                and card["statement"].startswith("Постройте")
                and role != "solution"
            ):
                errors.append("unexpected_asset_role")
            with Image.open(io.BytesIO(figure(visual["path"]))) as graphic:
                if graphic.format != "PNG" or min(graphic.size) < 240:
                    errors.append("invalid_asset")
                graphic.verify()
            asset_refs.append([role, visual["path"]])
        if len(card["hints"]) != 2 or len(card["solution_steps"]) < 2:
            errors.append("incomplete_teaching")
        records.append(
            {
                "task_id": task_id,
                "version": version,
                "number": number,
                "subtype": subtype,
                "automatic_check": "error" if errors else "passed",
                "issues": sorted(set(errors)),
                "independent_check": {
                    20: "solution_set_from_statement",
                    21: "exact_word_problem_model_from_statement",
                    22: "intersection_count_from_declared_branches",
                    23: "numerical_answer_from_statement",
                    25: "numerical_answer_from_statement",
                }.get(number, "not_automated"),
                "review": "pinned_review"
                if reviewed.get(task_id) == digest
                else "expert_review_needed",
                "assets": asset_refs,
                "editorial_findings": (
                    ["same_problem_cross_catalog_339709_97C87B"]
                    if card["source_id"] in {"339709", "97C87B"}
                    else []
                ),
                "editorial_revision": FIXED_PROOFS.get(card["source_id"]),
                "max_formula_width_px": max(widths, default=0),
            }
        )
    report.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    if any(r["issues"] for r in records):
        raise SystemExit([(r["task_id"], r["issues"]) for r in records if r["issues"]])
    if previews:
        previews.mkdir(parents=True, exist_ok=True)
        for number, samples in sorted(groups.items()):
            cards = [entry[1] for _, entry in sorted(samples.items())]
            for width in (360, 390):
                preview(number, cards, width, previews)
        for width in (360, 390):
            preview_feedback(width, previews)
    print(f"{len(records)} cards, {sum(map(len, groups.values()))} subtypes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=Path("reports/part2-presentation-audit.json")
    )
    parser.add_argument("--previews", type=Path, default=Path("reports/previews/part2"))
    args = parser.parse_args()
    audit(args.previews, args.report)
