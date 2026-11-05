"""Mobile photo views derived from immutable OGE 1–5 snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from io import BytesIO
from math import hypot, sqrt
from typing import cast
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont

from app.math.scenario_engine import ScenarioSnapshot
from app.math.scenarios.stories import FLAT, GARDEN, PAPER, STOVE, TARIFF, TYRES

INK = "#182e43"
BLUE = "#14568a"


@lru_cache
def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError("Install DejaVu Sans for Cyrillic scenario photos")


def png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def table(title: str, rows: list[list[str]], widths: tuple[int, ...]) -> bytes:
    width = sum(widths) + 40
    heights = [max(1, max(cell.count("\n") + 1 for cell in row)) * 44 + 24 for row in rows]
    image = Image.new("RGB", (width, 92 + sum(heights)), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 18), title, font=font(39), fill=INK)
    y = 76
    for index, (row, height) in enumerate(zip(rows, heights, strict=True)):
        x = 20
        for value, span in zip(row, widths, strict=True):
            draw.rectangle(
                (x, y, x + span, y + height),
                fill=("#e0ebf7" if not index else ("#f1f6fb" if index % 2 else "white")),
                outline="#adbed0",
                width=2,
            )
            size = 36
            while draw.multiline_textbbox((0, 0), value, font=font(size))[2] > span - 16:
                size -= 1
            draw.multiline_text(
                (x + span // 2, y + height // 2),
                value,
                font=font(size),
                fill=INK,
                anchor="mm",
                align="center",
            )
            x += span
        y += height
    return png(image)


def tariff_chart(context: Mapping[str, object]) -> bytes:
    image = Image.new("RGB", (960, 660), "white")
    draw = ImageDraw.Draw(image)
    for key, title, top, divisor in (
        ("minutes", "Звонки, мин", 20, 1),
        ("gb_quarters", "Интернет, ГБ", 340, 4),
    ):
        values = cast(tuple[int, ...], context[key])
        scale = 135 / max(1, max(values))
        points = [(61 + i * 76, top + 222 - round(value * scale)) for i, value in enumerate(values)]
        draw.text((24, top), title, font=font(39), fill=INK)
        draw.line((27, top + 222, 930, top + 222), fill=INK, width=3)
        draw.line(points, fill=BLUE, width=6)
        for i, ((x, y), value) in enumerate(zip(points, values, strict=True)):
            label = f"{value / divisor:g}".replace(".", ",")
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=BLUE)
            draw.text(
                (x, y - 10),
                label,
                font=font(29),
                fill=INK,
                anchor="mb",
                stroke_width=3,
                stroke_fill="white",
            )
            month = (
                "янв",
                "фев",
                "мар",
                "апр",
                "май",
                "июн",
                "июл",
                "авг",
                "сен",
                "окт",
                "ноя",
                "дек",
            )[i]
            draw.text((x, top + 248), month, font=font(30), fill=INK, anchor="mt")
    return png(image)


def garden_plan(snapshot: ScenarioSnapshot) -> bytes:
    if snapshot.context.get("world_version") == GARDEN.VERSION:
        return _garden_source_plan(snapshot)
    root = ElementTree.fromstring(GARDEN._svg(snapshot.context))
    image = Image.new("RGB", (990, 750), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 15), "План участка", font=font(44), fill=INK)

    def xy(x: int, y: int) -> tuple[int, int]:
        return (30 + (x - 20) * 3, 85 + (y - 20) * 3)

    for node in root.findall(".//*[@data-role]"):
        if node.tag.endswith("rect"):
            x, y, w, h = (int(node.attrib[k]) for k in ("x", "y", "width", "height"))
            draw.rectangle(
                (*xy(x, y), *xy(x + w, y + h)), fill=node.attrib["fill"], outline=INK, width=2
            )
    house = [(120, 20), (200, 20), (200, 80), (220, 80), (220, 100), (120, 100)]
    draw.polygon([xy(x, y) for x, y in house], fill="#e7b88e", outline=INK, width=4)
    paving = root.find(".//*[@data-role='paving']")
    if paving is not None and paving.tag.endswith("path"):
        draw.line(
            [xy(320, 120), xy(200, 120), xy(200, 180), xy(110, 180)], fill="#b99d6b", width=30
        )
    for x, y in ((50, 50), (75, 50), (50, 75)):
        cx, cy = xy(x, y)
        draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill="#478e42")
    for x in range(20, 321, 20):
        draw.line((*xy(x, 20), *xy(x, 220)), fill="#849486", width=1)
    for y in range(20, 221, 20):
        draw.line((*xy(20, y), *xy(320, y)), fill="#849486", width=1)
    boundary = [(320, 110), (320, 20), (20, 20), (20, 220), (320, 220), (320, 130)]
    draw.line([xy(x, y) for x, y in boundary], fill=INK, width=5)
    for label in root.findall(".//*[@data-label]"):
        cx, cy = xy(int(label.attrib["x"]), int(label.attrib["y"]))
        draw.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill="white", outline=INK, width=2)
        draw.text((cx, cy), label.text or "", font=font(37), fill=INK, anchor="mm")
    gate_x, gate_y = xy(320, 120)
    draw.line((gate_x + 48, gate_y, gate_x + 12, gate_y), fill=INK, width=5)
    draw.polygon(
        ((gate_x + 8, gate_y), (gate_x + 24, gate_y - 10), (gate_x + 24, gate_y + 10)), fill=INK
    )
    draw.text((28, 694), "Клетка — 2 м · дорожка — 1 м · стрелка — ворота", font=font(32), fill=INK)
    return png(image)


def _garden_source_plan(snapshot: ScenarioSnapshot) -> bytes:
    root = ElementTree.fromstring(GARDEN._svg(snapshot.context))
    image = Image.new("RGB", (990, 750), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 15), "План участка", font=font(44), fill=INK)

    def xy(x: int, y: int) -> tuple[int, int]:
        return 30 + (x - 20) * 3, 85 + (y - 20) * 3

    for x in range(20, 321, 20):
        draw.line((*xy(x, 20), *xy(x, 220)), fill="#849486", width=1)
    for y in range(20, 221, 20):
        draw.line((*xy(20, y), *xy(320, y)), fill="#849486", width=1)
    for node in root.findall(".//*[@data-role]"):
        if node.tag.endswith("rect"):
            x, y, width, height = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
            draw.rectangle(
                (*xy(x, y), *xy(x + width, y + height)),
                fill=node.attrib["fill"],
                outline=INK,
                width=2,
            )
        elif node.tag.endswith("polygon"):
            points = [tuple(map(int, point.split(","))) for point in node.attrib["points"].split()]
            draw.polygon(
                [xy(x, y) for x, y in points],
                fill=node.attrib["fill"],
                outline=INK,
                width=4,
            )
        elif node.tag.endswith("g") and node.attrib.get("data-role") == "orchard":
            for circle in node.findall(".//{*}circle"):
                x, y, radius = (int(circle.attrib[key]) for key in ("cx", "cy", "r"))
                cx, cy = xy(x, y)
                scaled = radius * 3
                draw.ellipse(
                    (cx - scaled, cy - scaled, cx + scaled, cy + scaled),
                    fill=node.attrib["fill"],
                )
    draw.line([xy(20, 20), xy(320, 20), xy(320, 120)], fill=INK, width=5)
    draw.line([xy(320, 140), xy(320, 220), xy(20, 220), xy(20, 20)], fill=INK, width=5)
    for label in root.findall(".//*[@data-label]"):
        cx, cy = xy(int(label.attrib["x"]), int(label.attrib["y"]))
        draw.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill="white", outline=INK, width=2)
        draw.text((cx, cy), label.text or "", font=font(37), fill=INK, anchor="mm")
    gate_x, gate_y = xy(320, 130)
    draw.line((gate_x + 48, gate_y, gate_x + 12, gate_y), fill=INK, width=5)
    draw.polygon(
        ((gate_x + 8, gate_y), (gate_x + 24, gate_y - 10), (gate_x + 24, gate_y + 10)), fill=INK
    )
    draw.text((28, 694), "Клетка — 2 м · дорожка — 1 м · стрелка — ворота", font=font(32), fill=INK)
    return png(image)


def garden_heating_table(snapshot: ScenarioSnapshot) -> bytes | None:
    """Render the source operands for current GARDEN snapshots; legacy snapshots omit them."""
    heat = cast(Mapping[str, object], snapshot.context.get("heat", {}))
    required = {
        "gas_heater_cost", "gas_installation_cost", "electric_heater_cost",
        "electric_installation_cost", "gas_m3_per_hour_tenths", "gas_price_per_m3_tenths",
        "electric_kw_tenths", "electric_price_per_kwh_tenths",
    }
    if not required.issubset(heat):
        return None
    rows = [
        ["Параметр", "Газовое отопление", "Электрическое отопление"],
        [
            "Нагреватель (котёл)",
            f"{int(cast(int, heat['gas_heater_cost'])):,}".replace(",", " ") + " руб.",
            f"{int(cast(int, heat['electric_heater_cost'])):,}".replace(",", " ") + " руб.",
        ],
        [
            "Прочее оборудование\nи монтаж",
            f"{int(cast(int, heat['gas_installation_cost'])):,}".replace(",", " ") + " руб.",
            f"{int(cast(int, heat['electric_installation_cost'])):,}".replace(",", " ") + " руб.",
        ],
        ["Расход / мощность",
         f"{int(cast(int, heat['gas_m3_per_hour_tenths'])) / 10:.1f} м³/ч",
         f"{int(cast(int, heat['electric_kw_tenths'])) / 10:.1f} кВт"],
        ["Цена ресурса",
         f"{int(cast(int, heat['gas_price_per_m3_tenths'])) / 10:.1f} руб./м³",
         f"{int(cast(int, heat['electric_price_per_kwh_tenths'])) / 10:.1f} руб./(кВт·ч)"],
    ]
    return table("Отопление: исходные данные", rows, (275, 250, 290))


def table_photos(snapshot: ScenarioSnapshot) -> tuple[bytes, ...]:
    c = snapshot.context
    story = snapshot.story_code
    if story == "TYRES":
        rims = cast(tuple[int, ...], c["table_rims"])
        rows = [["Ширина, мм", *(f"{rim}″" for rim in rims)]]
        for row in cast(tuple[Mapping[str, object], ...], c["table"]):
            width = int(cast(int, row["width_mm"]))
            cells = cast(tuple[tuple[int, ...], ...], row["aspect_ratios_by_rim"])
            rows.append(
                [
                    str(width),
                    *(
                        "\n".join(TYRES._tire_text(width, ratio, rim) for ratio in ratios) or "—"
                        for rim, ratios in zip(rims, cells, strict=True)
                    ),
                ]
            )
        return (table("Допустимые размеры шин", rows, (212, 240, 240, 240)),)
    if story == "PAPER":
        rows = [["Строка", "Длина, мм", "Ширина, мм"]]
        rows.extend(
            [str(i), str(length), str(width)]
            for i, (_, length, width) in enumerate(PAPER._get_rows(c), 1)
        )
        return (table("Размеры листов", rows, (235, 335, 335)),)
    if story == "STOVE":
        rows = [["№", "Тип печи", "Объём, м³", "Масса, кг", "Цена, руб."]]
        rows.extend(
            [
                str(r["id"]),
                str(r["kind"]),
                f"{r['min_m3']}–{r['max_m3']}",
                str(r["mass_kg"]),
                STOVE._money(cast(int, r["price_rub"])),
            ]
            for r in STOVE._rows(c)
        )
        return (table("Каталог печей", rows, (68, 248, 205, 181, 218)),)
    return ()


def flat_plan(snapshot: ScenarioSnapshot) -> bytes:
    legacy = snapshot.generator_version == FLAT.LEGACY_VERSION
    geometry, doors, windows = FLAT.plan_symbols(snapshot.generator_version)
    image = Image.new("RGB", (1000, 1030) if legacy else (1250, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 18), "План квартиры", font=font(45), fill=INK)
    labels = cast(Mapping[str, int], snapshot.context["room_labels"])

    def xy(x: int, y: int) -> tuple[int, int]:
        return (146 + 34 * x, 265 + 34 * y) if legacy else (60 + 34 * x, 150 + 34 * y)

    for room, parts in geometry.items():
        for x1, y1, x2, y2 in parts:
            draw.rectangle((*xy(x1, y1), *xy(x2, y2)), fill="#f4f8fc")
            for x in range(x1 + 1, x2):
                draw.line((*xy(x, y1), *xy(x, y2)), fill="#b3c5d6", width=2)
            for y in range(y1 + 1, y2):
                draw.line((*xy(x1, y), *xy(x2, y)), fill="#b3c5d6", width=2)
            draw.rectangle((*xy(x1, y1), *xy(x2, y2)), outline=INK, width=6)
        x1, y1, x2, y2 = parts[0]
        cx, cy = xy(x1 + x2, y1 + y2)
        cx, cy = (cx + (146 if legacy else 60)) // 2, (cy + (265 if legacy else 150)) // 2
        draw.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill="white", outline=INK, width=2)
        draw.text((cx, cy), str(labels[room]), font=font(40), fill=INK, anchor="mm")

    def opening(x: int, y: int, orientation: str, half: int, color: str) -> None:
        px, py = xy(x, y)
        ends = (
            (px - half, py, px + half, py) if orientation == "h" else (px, py - half, px, py + half)
        )
        draw.line(ends, fill="white", width=14)
        draw.line(ends, fill=color, width=8)

    if not legacy:
        draw.line((*xy(5, 13), *xy(10, 13)), fill="#b3c5d6", width=6)
    for x, y, direction in doors:
        opening(x, y, direction, 17, BLUE)
    for x, y, direction in windows:
        opening(x, y, direction, 30, "#008080")
    opening(7 if legacy else 10, 19 if legacy else 18, "h", 30, "#ad252c")
    draw.text(
        (384, 925) if legacy else (400, 780), "Вход", font=font(36), fill="#ad252c", anchor="mt"
    )
    draw.text(
        (32, 981) if legacy else (32, 846),
        "Клетка — 0,4 м · двери синие · окна бирюзовые",
        font=font(35),
        fill=INK,
    )
    return png(image)


def paper_diagram() -> bytes:
    image = Image.new("RGB", (940, 475), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 22), "Форматы бумаги серии A", font=font(44), fill=INK)
    x = 36
    for i in range(6):
        short = 205 / sqrt(2) ** i
        long = short * sqrt(2)
        width, height = (short, long) if i % 2 == 0 else (long, short)
        top = 410 - height
        draw.rectangle((x, top, x + width, 410), fill="#e5eff9", outline=INK, width=4)
        draw.text((x + width / 2, 420), f"A{i}", font=font(35), fill=INK, anchor="mt")
        x += round(width) + 24
    return png(image)


def tyre_diagram() -> bytes:
    image = Image.new("RGB", (960, 540), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 20), "Размеры шины и колеса", font=font(44), fill=INK)
    draw.text((215, 90), "Профиль шины", font=font(36), fill=INK, anchor="mt")
    draw.text((690, 90), "Вид сбоку", font=font(36), fill=INK, anchor="mt")
    draw.rounded_rectangle((100, 166, 330, 385), radius=50, fill="#94b7d5", outline=INK, width=5)
    draw.rounded_rectangle((138, 205, 292, 352), radius=40, fill="white", outline=INK, width=4)
    for radius, color in ((170, "#94b7d5"), (109, "#eaf2fa")):
        draw.ellipse(
            (690 - radius, 320 - radius, 690 + radius, 320 + radius),
            fill=color,
            outline=INK,
            width=5,
        )
    for line, label, position in (
        ((100, 423, 330, 423), "B", (215, 443)),
        ((356, 166, 356, 205), "H", (389, 165)),
        ((690, 211, 690, 429), "d", (722, 290)),
        ((500, 150, 500, 490), "D", (470, 290)),
    ):
        draw.line(line, fill=INK, width=4)
        x1, y1, x2, y2 = line
        for x, y in ((x1, y1), (x2, y2)):
            dx, dy = (0, 10) if y1 == y2 else (10, 0)
            draw.line((x - dx, y - dy, x + dx, y + dy), fill=INK, width=4)
        draw.text(position, label, font=font(37), fill=INK, anchor="mt")
    return png(image)


def stove_arc(context: Mapping[str, object]) -> bytes:
    width, height = (cast(int, context[key]) for key in ("arc_width_cm", "arc_height_cm"))
    half = width / 2
    radius = hypot(half, height)
    scale = min(610 / width, 360 / radius)
    image = Image.new("RGB", (960, 650), "white")
    draw = ImageDraw.Draw(image)
    draw.text((28, 20), "Арка кожуха печи", font=font(44), fill=INK)
    base = 485
    offsets = (-half + width * i / 100 for i in range(101))
    points = [(480 + x * scale, base - sqrt(radius**2 - x**2) * scale) for x in offsets]
    left, top = points[0]
    right, _ = points[-1]
    draw.line(points, fill=BLUE, width=7)
    draw.line([(left, top), (left, base), (right, base), (right, top)], fill=INK, width=4)
    draw.line((480, base, right, top), fill="#986225", width=5)
    draw.ellipse((473, base - 7, 487, base + 7), fill=INK)
    draw.text((495, base + 12), "O", font=font(38), fill=INK)
    draw.line((left, 560, right, 560), fill=INK, width=3)
    draw.line((left - 25, top, left - 25, base), fill=INK, width=3)
    for x in (left, right):
        draw.line((x, 548, x, 572), fill=INK, width=3)
    for y in (top, base):
        draw.line((left - 38, y, left - 12, y), fill=INK, width=3)
    draw.text((480, 580), f"{width} см", font=font(38), fill=INK, anchor="mt")
    draw.text((left - 45, (top + base) / 2), f"{height} см", font=font(36), fill=INK, anchor="rm")
    return png(image)


def scenario_photos(snapshot: ScenarioSnapshot) -> tuple[bytes, ...]:
    """Repaint the saved inputs for Telegram without changing stored assets or hashes."""
    story = snapshot.story_code
    if story == "TYRES":
        return (*table_photos(snapshot), tyre_diagram())
    if story == "PAPER":
        return (*table_photos(snapshot), paper_diagram())
    if story == "STOVE":
        return (*table_photos(snapshot), stove_arc(snapshot.context))
    if story == "TARIFF":
        root = ElementTree.fromstring(TARIFF.TariffRenderer._table_svg(snapshot.context))
        cells = [node.text or "" for node in root.iter() if node.tag.endswith("text")]
        rows = [cells[i : i + 4] for i in range(0, len(cells), 4)]
        for row in rows[1:]:
            row[0] = row[0].replace("Домашний-", "Домашний\n")
        return (
            tariff_chart(snapshot.context),
            table("Домашний интернет", rows, (200, 220, 210, 285)),
        )
    if story == "GARDEN":
        heating = garden_heating_table(snapshot)
        return (garden_plan(snapshot), *((heating,) if heating is not None else ()))
    if story == "FLAT":
        return (flat_plan(snapshot),)
    raise ValueError(f"No public mobile renderer for {story}")
