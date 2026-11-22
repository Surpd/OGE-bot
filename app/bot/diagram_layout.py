"""Delivery layouts for verified diagrams. Stored originals remain replayable."""

from fractions import Fraction
from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.math.oge07_graph import projection
from app.math.oge11_render import HEIGHT, PLOT, ROW_HEIGHT, WIDTH


def mobile_diagram(png: bytes, source: dict[str, Any]) -> bytes:
    family = str(source.get("family_id", ""))
    if family.startswith("OGE13-"):
        from app.math.inequalities import LEGACY_GENERATOR_VERSION, render_option_sheet_snapshot_png

        if source.get("generator_version") == LEGACY_GENERATOR_VERSION:
            return render_option_sheet_snapshot_png(source, mobile=True)
        return png
    graph_model = source.get("graph_model")
    if not (family.startswith(("OGE11-", "OGE16-")) or family.startswith("OGE07-") and graph_model):
        return png
    with Image.open(BytesIO(png)) as original:
        image = original.convert("RGB")
    if family.startswith("OGE11-") and image.size == (WIDTH, HEIGHT):
        # Copy all axis, scale and curve pixels from the verified original.
        layout = Image.new("RGB", (848, 864), "white")
        for i, (left, top) in enumerate(((10, 5), (434, 5), (222, 436))):
            row = ROW_HEIGHT * i
            plot = image.crop((PLOT[0] - 2, row + PLOT[1] - 2, PLOT[2] + 3, row + PLOT[3] + 3))
            layout.paste(plot, (left, top + 30))
            layout.paste(image.crop((24, row + 18, 44, row + 46)), (left, top))
        image = layout
    elif family.startswith("OGE16-"):
        bbox = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        if bbox:
            left, top, right, bottom = bbox
            image = image.crop(
                (
                    max(0, left - 16),
                    max(0, top - 16),
                    min(image.width, right + 16),
                    min(image.height, bottom + 16),
                )
            )
        image.thumbnail((680, 620), Image.Resampling.LANCZOS)
    elif family.startswith("OGE07-") and graph_model and image.size == (960, 260):
        # Two label bands in the v2/v3 scene do not contain axis or mark pixels.
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 80, 959, 110), fill="white")
        draw.rectangle((0, 165, 959, 200), fill="white")
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
        positions = projection(graph_model)
        for p in graph_model["points"]:
            draw.text((positions[p["id"]], 108), p["label"], font=font, fill="#1a2434", anchor="mb")
        lo, hi = (Fraction(*graph_model[k]) for k in ("axis_min", "axis_max"))
        for tick in graph_model["ticks"]:
            x = 72 + round((Fraction(*tick["value"]) - lo) * 816 / (hi - lo))
            draw.text((x, 165), tick["label"], font=font, fill="#1a2434", anchor="mt")
        image = image.crop((0, 59, 960, 215))
    else:
        return png
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
