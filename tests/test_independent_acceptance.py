import re
from fractions import Fraction
from io import BytesIO
from math import gcd

import pytest
from PIL import Image, ImageChops

from app.bot.family_display import typeset_family_text
from app.bot.presentation import format_rich_message
from app.math import oge11, oge18, oge19
from app.math.generator import generate, training_rejection
from app.math.inequalities import Interval, _render_option_sets_png
from app.math.oge8 import R05
from app.math.oge8_scheduler import build_task8_candidate_batch
from app.math.oge18_oracle import answer_family
from app.math.oge18_render import VERSION_V3, polygon_construction
from app.math.oge19_scheduler import build_task19_candidate_batch
from app.math.scheduler import build_candidate_batch


def test_denominators_and_radicals_require_the_intended_operation_in_actual_issues():
    family = "OGE06-F001-SUB"
    old = next(generate(family, s) for s in range(50) if training_rejection(generate(family, s)))
    a, b, c, d = map(int, re.findall(r"\d+", old.condition))
    assert b == d and Fraction(old.correct_answer.replace(",", ".")) == Fraction(a - c, b)
    for seed in range(24):
        for item in build_candidate_batch({"family_queue": [family]}, seed):
            a, b, c, d = map(int, re.findall(r"\d+", item["condition"]))
            assert b != d and Fraction(a, b) - Fraction(c, d) == Fraction(
                item["correct_answer"].replace(",", ".")
            )
        items = build_task8_candidate_batch({"family_queue": [R05]}, seed)
        assert items
        for item in items:
            a, b, c = item["parameters"]
            assert c not in (a, b)
            assert Fraction(a * b, c) == Fraction(item["correct_answer"].replace(",", ".")) ** 2


def test_school_notation_preserves_the_operator_and_prose_boundary():
    html = format_rich_message("Выразим C: C = (F − 32) · 5/9.")
    assert r"\div" not in html and ":</" not in html and ": " in html
    assert r"\div" in format_rich_message("Вычислите 12 : 3.")
    assert r"\sqrt{49}" in format_rich_message("Вычислите √(49).")
    assert "−0" not in typeset_family_text("(x+4)(x−0)>0", "OGE13-Q03")
    assert "≤" in typeset_family_text("x <= 0", "OGE13-S03")
    assert "Площадь треугольника MBN" in typeset_family_text("S_MBN = 25.5", "OGE15-F13")
    assert "25,5" in typeset_family_text("Ответ: 25.5", "OGE15-F13")
    assert "знает" in typeset_family_text("21 знают оба языка", "OGE10-P01")
    trig = format_rich_message("Стороны равны d · sin α и d · cos α; cos α = 0,8.")
    assert trig.count(r"\cos \alpha") == 2 and trig.count(r"\sin \alpha") == 1
    assert trig.count("<tg-math>") == 3
    assert "7² + 24²" in typeset_family_text("sin = 7/25", "OGE16-C06")


@pytest.mark.parametrize("family", oge11.FAMILIES)
def test_graph_reasoning_identifies_all_three_matches_and_legacy_pixels(family):
    old = oge11.generate(family, 4, generator_version="0.2.0")
    item = oge11.generate(family, 4)
    assert old.png_bytes == item.png_bytes and old.correct_answer == item.correct_answer
    replay = typeset_family_text("\n".join(old.solution), old.to_snapshot())
    for step, index, answer in zip(
        item.solution[:3], item.letter_graph_ids, item.correct_answer, strict=True
    ):
        graph = item.graphs[index]
        assert item.digit_graph_ids[int(answer) - 1] == index
        assert f" {answer}." in step
        if graph.kind == "linear":
            assert str(graph.value(Fraction(1)) - graph.value(Fraction(0))) in step
        elif graph.kind == "inverse":
            assert str(2 * graph.value(Fraction(2))) in step
        elif graph.kind == "quadratic":
            assert str(graph.value(Fraction(0))) in step
        else:
            assert str(graph.value(Fraction(-3))) in step
    assert not re.search("linear|inverse|constant|quadratic", replay)


@pytest.mark.parametrize("width", (360, 390, 430))
def test_close_interval_endpoints_remain_distinct_on_the_actual_scaled_png(width):
    lo, hi = Fraction(-9, 5), Fraction(-8, 5)
    options = tuple(
        (Interval(lo, hi, left, right),)
        for left, right in ((False, False), (True, False), (False, True), (True, True))
    )
    with Image.open(BytesIO(_render_option_sets_png(options))) as im:
        small = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
    for i, (interval,) in enumerate(options):
        y = round((185 + i * 250) * small.height / 1120)
        for x, closed in ((220, interval.left_closed), (1060, interval.right_closed)):
            px = round(x * width / 1280)
            red, _, blue = small.getpixel((px, y))
            assert (blue - red > 65) == closed
            assert min(small.getpixel((px + dx, y))[0] for dx in range(-5, 6)) < 110


def lattice_area(points):
    """Pick's theorem; odd ray crossings classify strict interior lattice points."""
    edges = list(zip(points, (*points[1:], points[0]), strict=True))
    boundary = sum(gcd(abs(u - x), abs(v - y)) for (x, y), (u, v) in edges)
    interior = 0
    for x in range(min(p[0] for p in points), max(p[0] for p in points) + 1):
        for y in range(min(p[1] for p in points), max(p[1] for p in points) + 1):
            if any(
                (x - a) * (d - b) == (y - b) * (c - a)
                and min(a, c) <= x <= max(a, c)
                and min(b, d) <= y <= max(b, d)
                for (a, b), (c, d) in edges
            ):
                continue
            interior += (
                sum(
                    (b > y) != (d > y) and x < a + Fraction((y - b) * (c - a), d - b)
                    for (a, b), (c, d) in edges
                )
                % 2
            )
    return interior + Fraction(boundary, 2) - 1


@pytest.mark.parametrize(
    "family,coordinates,area",
    (
        ("OGE18-A06", [(2, 2), (4, 2), (5, 4), (2, 6)], 8),
        ("OGE18-A07", [(2, 2), (6, 2), (6, 3), (4, 3), (4, 5), (5, 5), (5, 6), (2, 6)], 11),
    ),
)
def test_source_shapes_and_generated_polygons(family, coordinates, area):
    assert lattice_area(coordinates) == answer_family(family, tuple(coordinates)) == area
    for seed in range(32):
        item = oge18.generate(family, seed, oge18.GENERATOR_VERSION_V2, renderer_version=VERSION_V3)
        snap = item.to_snapshot()
        points = tuple(tuple(p) for p in snap["points"])
        assert lattice_area(points) == Fraction(snap["correct_answer"])
        if seed == 0:
            assert oge18.from_snapshot(snap).png_bytes == item.png_bytes
            with (
                Image.open(BytesIO(item.png_bytes)) as source,
                Image.open(BytesIO(polygon_construction(family, points))) as explanation,
            ):
                assert ImageChops.difference(source, explanation).getbbox()
            with pytest.raises(ValueError):
                answer_family(family, (*points[:-1], points[0]))


def test_requested_claims_match_the_reviewed_keys_across_restarted_cycles():
    state = {"question_phase": 0}
    for step in range(16):
        item = build_task19_candidate_batch(state, 1000 + step)[0]
        false = step % 4 >= 2
        assert (item["question_kind"] == "find_false") == false
        assert ("Тренировочный вариант" in item["condition"]) == false
        key = "".join(
            str(i)
            for i, s in enumerate(item["statements"], 1)
            if oge19.STATEMENTS_BY_ID[s["id"]].is_true != false
        )
        assert len(key) == 1 + step % 2
        assert oge19.restore(item).answer_mask == key
        assert oge19.check_answer(item, key[::-1])
        state = {
            "question_phase": item["_question_phase_after"],
            "family_queue": item["_family_queue_after"],
            "correct_position_counts": item["_correct_position_counts_after"],
        }
    old = oge19.generate(7, generator_version="oge19-triples-4")
    assert oge19.restore(old.snapshot()).answer_mask == old.answer_mask


def test_demo_disk_area_ratio_and_unmarked_source_at_mobile_sizes():
    from app.math.oge18_disks import audit, render

    # FIPI 2026. Small radius one unit, large disk circumscribes a 2 by 2 square.
    pts = ((8, 8), (9, 8), (5, 6), (6, 7))
    assert answer_family("OGE18-C01", pts) == 2
    png = render(pts)
    audit(png, pts)
    with pytest.raises(ValueError):
        audit(render(pts, construction=True), pts)
    with pytest.raises(ValueError):
        answer_family("OGE18-C01", ((3, 3), (4, 3), (4, 4), (5, 5)))
    for width in (360, 390, 430):
        with Image.open(BytesIO(png)) as image:
            small = image.resize(
                (width, round(image.height * width / image.width)), Image.Resampling.LANCZOS
            )
            # Both circle interiors stay white between grid lines.
            assert small.convert("L").histogram()[255] > small.width * small.height // 2


async def test_fixed_disk_family_exhausts_and_restarts_its_five_shapes():
    from app.math.oge18_scheduler import build_task18_candidate_batch
    from app.persistence.repository import MemoryRepository
    from app.persistence.rotation_history import ordinary_state

    repo = MemoryRepository()
    user = 719
    await repo.ensure_task18_session(user)
    pid = None
    emitted = []
    for seed in range(11):
        saved = await repo.task18_state(user)
        state = await ordinary_state(repo, user, 18, saved["state"])
        batch = build_task18_candidate_batch(state, seed, enabled_families=("OGE18-C01",))
        issued = await repo.advance_task18_problem(user, pid, batch, skip_active=pid is not None)
        assert issued["_transitioned"]
        pid = issued["problem_id"]
        emitted.append(issued["fingerprint"])
    assert len(set(emitted[:5])) == len(set(emitted[5:10])) == 5
    assert all(a != b for a, b in zip(emitted, emitted[1:], strict=False))
    assert len(repo.issued18[user]) == 11


def test_three_relaid_graphs_retain_every_curve_and_axis_pixel():
    from app.bot.diagram_layout import mobile_diagram
    from app.math.oge11_render import PLOT, ROW_HEIGHT

    problem = oge11.generate("OGE11-F08", 14)
    with (
        Image.open(BytesIO(problem.png_bytes)) as original,
        Image.open(BytesIO(mobile_diagram(problem.png_bytes, problem.to_snapshot()))) as delivered,
    ):
        for i, (x, y) in enumerate(((10, 35), (434, 35), (222, 466))):
            row = ROW_HEIGHT * i
            before = original.convert("RGB").crop(
                (PLOT[0] - 2, row + PLOT[1] - 2, PLOT[2] + 3, row + PLOT[3] + 3)
            )
            after = delivered.crop((x, y, x + before.width, y + before.height))
            assert ImageChops.difference(before, after).getbbox() is None


def test_pedagogical_edits_retain_values_and_physical_assumptions():
    from app.bot.learner_math import learner_text
    from app.math.progressions import A02, generate

    family = "OGE14-G02"
    assert learner_text("Через 4 интервалов прошло 104 минут", family) == (
        "Через 4 интервала прошло 104 мин"
    )
    assert learner_text("ровно 4 раз", family) == "ровно 4 раза"
    assert "проезжал на 8 м меньше" in learner_text(
        "каждую следующую секунду тормозной путь уменьшался на 8 м", "OGE14-A09"
    )
    assert "полностью погружённого" in learner_text("для тела в воде", "OGE12-R012")
    assert "без потери массы" in learner_text(
        "половина вещества А превращается в вещество Б.", family
    )
    q = generate(A02, 14).to_snapshot()
    p = q["parameters"]
    numbers = re.findall(r"\d+", q["condition"])
    rows, i, a, j, b = map(int, numbers[:5])
    step = Fraction(b - a, j - i)
    assert step == p["d"] and b + (rows - j) * step == int(q["correct_answer"])
    solution = typeset_family_text("\n".join(q["solution"]), q)
    assert f"{j} до последнего" in solution and str(b) in solution


def test_archived_inequality_can_be_zoomed_without_regenerating_the_question():
    from app.bot.diagram_layout import mobile_diagram
    from app.math.inequalities import LEGACY_GENERATOR_VERSION, generate, render_option_sheet_png

    old = generate("OGE13-S01", 2701, LEGACY_GENERATOR_VERSION)
    current = generate("OGE13-S01", 2701)
    stored = old.to_snapshot()
    raw = render_option_sheet_png(old)
    assert current.options == old.options
    assert current.correct_option_number == old.correct_option_number
    assert mobile_diagram(raw, stored) == render_option_sheet_png(current)
    assert old.to_snapshot() == stored


def test_written_proof_distinguishes_tangents_from_corresponding_radii():
    import json

    from app.persistence.part2_bank import ATLAS

    records = {
        c["task_id"]: c for c in map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines())
    }
    card = records["oge-part2-atlas-a24-common-tangent-ratio-05"]
    # The tangent is the x-axis. P=(0,0), O₁=(-6,3), O₂=(10,-5).
    # Signed heights and the positions of the two feet determine all lengths.
    lengths = {"PT₁": 6, "PT₂": 10, "O₁T₁": 3, "O₂T₂": 5}
    a, b, c, d = re.search(r"(PT₁)/(\w+) = (\w+)/(\w+)\.", card["reference_solution"]).groups()
    assert Fraction(lengths[a], lengths[b]) == Fraction(lengths[c], lengths[d]) == Fraction(3, 5)
    assert card["content_version"] == 2
    secants = records["oge-part2-atlas-a24-cyclic-external-03"]
    assert "MA = MC" in secants["statement"] and secants["content_version"] == 2


@pytest.mark.parametrize(
    ("seed", "same_theorem"),
    [
        (39, {"OGE19-A164", "OGE19-A009"}),
        (72, {"OGE19-A027", "OGE19-A169"}),
    ],
)
def test_source_cards_with_the_same_theorem_cannot_appear_together(seed, same_theorem):
    old = oge19.generate(seed, theme="triangles", generator_version="oge19-triples-4")
    assert same_theorem <= {s.id for s in old.statements}
    assert oge19.restore(old.snapshot()).answer_mask == old.answer_mask
    forged = old.snapshot()
    forged.update(generator_version=oge19.GENERATOR_VERSION, question_kind="find_true")
    oge19.refresh_snapshot_digest(forged)
    with pytest.raises(ValueError, match="Incompatible statements"):
        oge19.validate_snapshot(forged)
    current = oge19.generate(seed, theme="triangles")
    assert not same_theorem <= {s.id for s in current.statements}


def test_counterexamples_are_readable_without_english_congruence_codes():
    from app.bot.learner_math import learner_text

    bank = {s.id: s for s in oge19.STATEMENTS}
    for key, visible in (("A165", "угол при вершине"), ("A025", "угол, который лежит не между")):
        text = learner_text(bank["OGE19-" + key].explanation, "OGE19-TRIANGLES")
        assert visible in text
    assert learner_text("Сторона AC занимает 21 клеток.", "OGE18-M01").endswith("21 клетку.")
