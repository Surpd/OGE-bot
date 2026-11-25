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
                fill=("#edf0f2" if not index else "white"),
                outline="#8c969e",
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
    image = Image.new("RGB", (960, 659), "white")
    draw = ImageDraw.Draw(image)
    minutes_color, internet_color = "#ad430e", "#14568a"
    left, right, top, bottom, step = 104, 856, 84, 564, 30
    months = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
    month_x = [128 + i * 64 for i in range(len(months))]
    axis_font = font(34)

    # A grid step represents 25 minutes on the left and 0.25 GB on the right.
    for quarter in range(17):
        y = bottom - step * quarter
        major = quarter % 2 == 0
        draw.line((left, y, right, y), fill="#b0bac3" if major else "#d8dfe5", width=2)
        if major:
            draw.text((left - 12, y), str(25 * quarter), font=axis_font, fill=INK, anchor="rm")
            label = f"{quarter / 4:g}".replace(".", ",")
            draw.text((right + 12, y), label, font=axis_font, fill=INK, anchor="lm")

    for index, (x, month) in enumerate(zip(month_x, months, strict=True), 1):
        draw.line((x, top, x, bottom), fill="#d8dfe5", width=2)
        draw.text((x, bottom + 12), str(index), font=axis_font, fill=INK, anchor="mt")
        draw.text((x, bottom + 52), month, font=font(26), fill=INK, anchor="mt")

    draw.line(((left, top), (left, bottom), (right, bottom), (right, top)), fill=INK, width=3)
    for x in (left, right):
        draw.polygon(((x, top - 10), (x - 6, top + 5), (x + 6, top + 5)), fill=INK)

    minute_points = list(
        zip(
            month_x,
            (bottom - step * (v // 25) for v in cast(tuple[int, ...], context["minutes"])),
            strict=True,
        )
    )
    internet_points = list(
        zip(
            month_x,
            (bottom - step * v for v in cast(tuple[int, ...], context["gb_quarters"])),
            strict=True,
        )
    )
    draw.line(minute_points, fill=minutes_color, width=6)
    for (x1, y1), (x2, y2) in zip(internet_points[:-1], internet_points[1:], strict=True):
        dx, dy = x2 - x1, y2 - y1
        length = hypot(dx, dy)
        for offset in range(0, round(length), 30):
            start, end = offset / length, min(offset + 17, length) / length
            draw.line(
                (x1 + start * dx, y1 + start * dy, x1 + end * dx, y1 + end * dy),
                fill=internet_color,
                width=6,
            )
    for x, y in minute_points:
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=minutes_color)
    # A hollow diamond leaves the minutes dot visible when both series coincide.
    for x, y in internet_points:
        draw.polygon(
            ((x, y - 13), (x + 13, y), (x, y + 13), (x - 13, y)),
            outline=internet_color,
            width=4,
        )

    draw.line((23, 39, 85, 39), fill=minutes_color, width=6)
    draw.text((97, 39), "Минуты", font=axis_font, fill=INK, anchor="lm")
    for x in (600, 623, 646):
        draw.line((x, 39, x + 13, 39), fill=internet_color, width=6)
    draw.text((674, 39), "Интернет, ГБ", font=axis_font, fill=INK, anchor="lm")
    return png(image)


def garden_plan(snapshot: ScenarioSnapshot) -> bytes:
    if snapshot.context.get("world_version") in GARDEN.SOURCE_PLAN_VERSIONS:
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

    surfaces = {
        "paving": "#e5bf85", "pad": "#eed5ac", "garden": "#f6f7f1",
        "greenhouse": "#e2e9e6", "orchard": "#546351",
    }
    for node in root.findall(".//*[@data-role]"):
        fill = surfaces.get(node.attrib["data-role"], "#e4d4bf")
        if node.tag.endswith("rect"):
            x, y, width, height = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
            draw.rectangle(
                (*xy(x, y), *xy(x + width, y + height)),
                fill=fill,
                outline=INK,
                width=2,
            )
        elif node.tag.endswith("polygon"):
            points = [tuple(map(int, point.split(","))) for point in node.attrib["points"].split()]
            draw.polygon(
                [xy(x, y) for x, y in points],
                fill=fill,
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
                    fill=fill,
                )
    # The cell scale must also be readable inside the house and paved area.
    grid = ImageDraw.Draw(image, "RGBA")
    for x in range(20, 321, 20):
        grid.line((*xy(x, 20), *xy(x, 220)), fill=(45, 53, 57, 68), width=2)
    for y in range(20, 221, 20):
        grid.line((*xy(20, y), *xy(320, y)), fill=(45, 53, 57, 68), width=2)
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
    highlight_loggias = snapshot.generator_version == FLAT.GENERATOR_VERSION
    geometry, doors, windows = FLAT.plan_symbols(snapshot.generator_version)
    image = Image.new("RGB", (1000, 1030) if legacy else (1250, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 18), "План квартиры", font=font(45), fill=INK)
    labels = cast(Mapping[str, int], snapshot.context["room_labels"])

    def xy(x: int, y: int) -> tuple[int, int]:
        return (146 + 34 * x, 265 + 34 * y) if legacy else (60 + 34 * x, 150 + 34 * y)

    for room, parts in geometry.items():
        fill = "#ffebba" if highlight_loggias and room.startswith("loggia_") else "#f4f8fc"
        for x1, y1, x2, y2 in parts:
            draw.rectangle((*xy(x1, y1), *xy(x2, y2)), fill=fill)
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
        (32, 981) if legacy else (32, 828 if highlight_loggias else 846),
        "Клетка — 0,4 м · двери синие · окна бирюзовые",
        font=font(35),
        fill=INK,
    )
    if highlight_loggias:
        draw.rectangle((32, 870, 53, 890), fill="#ffebba", outline=INK)
        draw.text((64, 862), "Лоджии выделены цветом", font=font(29), fill=INK)
    return png(image)


def paper_diagram() -> bytes:
    image = Image.new("RGB", (900, 714), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 16), "Деление листа A0", font=font(44), fill=INK)
    left, top = 34, 90
    right = image.width - left
    bottom = top + round((right - left) / sqrt(2))
    draw.rectangle((left, top, right, bottom), outline=INK, width=4)
    for index in range(1, 6):
        if right - left > bottom - top:
            middle = (left + right) // 2
            draw.line((middle, top, middle, bottom), fill=INK, width=3)
            center = ((right + middle) // 2, (top + bottom) // 2)
            right = middle
        else:
            middle = (top + bottom) // 2
            draw.line((left, middle, right, middle), fill=INK, width=3)
            center = ((left + right) // 2, (middle + bottom) // 2)
            bottom = middle
        draw.text(center, f"A{index}", font=font(40), fill=INK, anchor="mm")
    return png(image)


def tyre_diagram() -> bytes:
    image = Image.new("RGB", (960, 540), "white")
    draw = ImageDraw.Draw(image)
    draw.text((32, 20), "Размеры шины и колеса", font=font(44), fill=INK)
    draw.text((215, 90), "Профиль шины", font=font(36), fill=INK, anchor="mt")
    draw.text((690, 90), "Вид сбоку", font=font(36), fill=INK, anchor="mt")
    draw.rounded_rectangle((100, 166, 330, 385), radius=50, fill="#e3e5e7", outline=INK, width=5)
    draw.rounded_rectangle((138, 205, 292, 352), radius=40, fill="white", outline=INK, width=4)
    for radius, color in ((170, "#e3e5e7"), (109, "white")):
        draw.ellipse(
            (690 - radius, 320 - radius, 690 + radius, 320 + radius),
            fill=color,
            outline=INK,
            width=5,
        )
    # Extension lines project the actual diameters onto the dimension lines.
    for y, left in ((150, 438), (211, 501), (429, 501), (490, 438)):
        draw.line((left, y, 690, y), fill="#78818a", width=2)
    for x in (100, 330):
        draw.line((x, 338, x, 433), fill="#78818a", width=2)
    for line, label, position in (
        ((100, 423, 330, 423), "B", (215, 440)),
        ((510, 150, 510, 211), "H", (486, 163)),
        ((510, 211, 510, 429), "d", (486, 299)),
        ((448, 150, 448, 490), "D", (418, 299)),
    ):
        x1, y1, x2, y2 = line
        draw.line(line, fill=INK, width=3)
        for x, y, direction in ((x1, y1, 1), (x2, y2, -1)):
            if y1 == y2:
                tip = [(x, y), (x + direction * 12, y - 5), (x + direction * 12, y + 5)]
            else:
                tip = [(x, y), (x - 5, y + direction * 12), (x + 5, y + direction * 12)]
            draw.polygon(tip, fill=INK)
        draw.text(position, label, font=font(36), fill=INK, anchor="mt")
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


_SHARED_PHOTO_INDEXES: dict[str, tuple[int, ...]] = {
    "TYRES": (1,),  # tire diagram
    "PAPER": (1,),  # paper-format diagram
}
_QUESTION_PHOTO_INDEXES: dict[str, tuple[int, ...]] = {
    "TYRES-TABLE-EXTREME": (0,),
    "PAPER-F01": (0,),
    "PAPER-F03": (0,),
    "PAPER-F04": (0,),
    "PAPER-F06": (0,),
    "PAPER-F07": (0,),
    "STOVE-F01-CAPACITY-LIMITS": (0,),
    "STOVE-F06-PURCHASE-EXTRA-COSTS": (0,),
    "STOVE-F07-FIT-WOOD-DELIVERY": (0,),
    "STOVE-F08-COST-COMPARISON": (0,),
    "STOVE-F09-DIRECT-DISCOUNT": (0,),
    "STOVE-F10-REVERSE-DISCOUNT": (0,),
    "STOVE-F02-ATTRIBUTE-MATCH": (0,),
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": (0,),
    "STOVE-F12-ARCH-RADIUS": (1,),
    "TARIFF-F01-MONTHS-MINUTES": (0,),
    "TARIFF-F04-MONTHLY-BILL": (0,),
    "TARIFF-F05-EXTREMUM": (0,),
    "TARIFF-F12-HOME-ISP": (1,),
    "GARDEN-01-IDENTIFY": (0,),
    "GARDEN-02-TILES-PACKS": (0,),
    "GARDEN-04-PERIMETER-POLYGON": (0,),
    "GARDEN-07-PERCENT-BUILDINGS": (0,),
    "GARDEN-09-HEAT-BREAKEVEN": (1,),
    "FLAT-01-ROOM-MATCH": (0,),
    "FLAT-02-TILE-PACK": (0,),
    "FLAT-02-PARQUET-PACK": (0,),
    "FLAT-03-RECT-AREA": (0,),
    "FLAT-04-RECT-PERCENT": (0,),
}


def _photo_indexes(snapshot: ScenarioSnapshot, position: int) -> tuple[int, ...]:
    if position not in range(1, 6):
        raise ValueError("Scenario question position must be between 1 and 5")
    question = next((item for item in snapshot.questions if item.position == position), None)
    if question is None:
        raise ValueError("Question is not present in the scenario snapshot")
    return (
        *_SHARED_PHOTO_INDEXES.get(snapshot.story_code, ()),
        *_QUESTION_PHOTO_INDEXES.get(question.family_id, ()),
    )


def scenario_photos_for_question(
    snapshot: ScenarioSnapshot, position: int, *, previous_position: int | None = None,
) -> tuple[bytes, ...]:
    """Select required materials, omitting ones already shown in an adjacent question."""
    indexes = _photo_indexes(snapshot, position)
    if previous_position is not None:
        previous = set(_photo_indexes(snapshot, previous_position))
        indexes = tuple(index for index in indexes if index not in previous)
    if not indexes:
        return ()
    if any(index < 0 for index in indexes):
        raise ValueError("Question material index cannot be negative")
    photos = scenario_photos(snapshot)
    # Some pre-table GARDEN snapshots legitimately have no heating PNG. Keep
    # those immutable legacy sessions resumable instead of failing to render.
    missing = [index for index in indexes if index >= len(photos)]
    if missing and not (
        snapshot.story_code == "GARDEN" and missing == [1]
        and snapshot.generator_version in {"garden-sosnovka-1.0", "garden-sosnovka-1.1",
                                           "garden-sosnovka-1.2", "garden-sosnovka-1.3"}
    ):
        raise ValueError("Required scenario material is missing")
    return tuple(photos[index] for index in dict.fromkeys(indexes) if index < len(photos))
