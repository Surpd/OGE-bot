"""Version 1 diagrams for the saved №10 probability model."""

from collections.abc import Mapping
from fractions import Fraction
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from app.math.probability import (
    EQUAL_POINTS,
    EULER_COUNTS,
    GRAPH_FAMILIES,
    PROBABILITY_TREE,
    WEIGHTED_POINTS,
    generate,
)


def render_snapshot(snapshot: Mapping[str, object]) -> bytes:
    family, seed = snapshot.get("family_id"), snapshot.get("seed")
    if family not in GRAPH_FAMILIES or not isinstance(family, str) or type(seed) is not int:
        raise ValueError("Missing diagram identity")
    problem = generate(family, seed, str(snapshot.get("generator_version")))
    expected = problem.to_snapshot()
    for key in ("diagram_version", "diagram", "condition", "correct_answer", "fingerprint"):
        if snapshot.get(key) != expected[key]:
            raise ValueError("Inconsistent saved probability diagram")
    image = Image.new("RGB", (720, 420 if family == PROBABILITY_TREE else 320), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 35)

    def label(x: int, y: int, text: str) -> None:
        draw.text(
            (x, y),
            text,
            anchor="mm",
            font=font,
            fill="#152637",
            stroke_width=2,
            stroke_fill="white",
        )

    if family == PROBABILITY_TREE:
        a, left, right = problem.diagram

        def branch(x: int, y: int, dx: int, probability: int, text: str) -> None:
            draw.line((x, y, x + dx, y + 145), fill="#314758", width=3)
            label(x + dx // 2, y + 72, f"0,{probability}")
            label(x + dx, y + 145, text)

        for dx, probability, name, conditional in ((-175, a, "A", left), (175, 10 - a, "A̅", right)):
            branch(360, 45, dx, probability, name)
            branch(360 + dx, 190, -90, conditional, "B")
            branch(360 + dx, 190, 90, 10 - conditional, "B̅")
            label(360 + dx, 190, name)
        label(360, 45, "S")
    else:
        draw.rectangle((8, 8, 712, 312), outline="#44586b", width=3)
        for x in (72, 271):
            draw.ellipse((x, 78, x + 376, 273), outline="#254968", width=4)
        label(95, 61, "A")
        label(625, 61, "B")
        if family == EQUAL_POINTS:
            regions = (
                (
                    (150, 145),
                    (220, 198),
                    (135, 189),
                    (200, 126),
                    (242, 160),
                    (180, 170),
                    (188, 221),
                ),
                (
                    (360, 153),
                    (335, 190),
                    (390, 174),
                    (367, 212),
                    (328, 159),
                    (380, 134),
                    (355, 183),
                ),
                (
                    (516, 158),
                    (558, 196),
                    (485, 130),
                    (488, 197),
                    (570, 149),
                    (535, 221),
                    (540, 173),
                ),
                ((360, 42), (148, 286), (550, 55), (655, 278), (230, 48), (56, 135), (433, 289)),
            )
            for points, count in zip(regions, problem.diagram, strict=True):
                for x, y in points[:count]:
                    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#182b36")
        else:
            positions: tuple[tuple[int, int], ...] = ((186, 178), (360, 178), (537, 178), (180, 45))
            if family == WEIGHTED_POINTS:
                positions = (
                    (178, 136),
                    (178, 213),
                    (360, 145),
                    (360, 213),
                    (539, 136),
                    (539, 213),
                    (360, 40),
                    (505, 290),
                )
            for (x, y), value in zip(positions, problem.diagram, strict=True):
                text = str(value) if family == EULER_COUNTS else problem_decimal(value)
                if family == WEIGHTED_POINTS:
                    draw.ellipse((x - 43, y - 5, x - 33, y + 5), fill="#152637")
                    x += 10
                label(x, y, text)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def problem_decimal(hundredths: int) -> str:
    from app.math.probability import ANSWER_POLICY

    return ANSWER_POLICY.format(Fraction(hundredths, 100)).replace(".", ",")
