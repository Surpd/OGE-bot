from io import BytesIO

import pytest
from PIL import Image

from app.bot.visual_cards import CardLayoutError, _Canvas, render_card
from app.bot.visual_models import (
    VisualBreakdown,
    VisualCard,
    VisualEntry,
    VisualMetric,
    VisualPractice,
    VisualSection,
)


def _png(card: VisualCard) -> Image.Image:
    data = render_card(card)
    with Image.open(BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.width == 1200
        assert image.height <= 2700
        assert len(data) < 10 * 1024 * 1024
        return image.copy()


@pytest.fixture
def transcript(monkeypatch):
    entries = []
    original = _Canvas.text

    def record(canvas, x, y, text, size, **kwargs):
        entries.append((x, y, text))
        original(canvas, x, y, text, size, **kwargs)

    monkeypatch.setattr(_Canvas, "text", record)
    return entries


def test_welcome_matches_brand_and_hero_palette():
    card = VisualCard("welcome", "Математика для ОГЭ", "Тренажёр первой части")
    image = _png(card)

    assert image.size == (1200, 579)
    points = ((0, 0), (25, 38), (33, 62), (349, 113), (356, 158))
    assert [image.getpixel((x * 3, y * 3)) for x, y in points] == [
        (248, 244, 233), (241, 94, 69), (230, 235, 223), (217, 226, 208), (230, 235, 223),
    ]
    assert render_card(card) == render_card(card)


def test_number_tiles_fit_complete_geometry_names_in_approved_columns(transcript):
    card = VisualCard("numbers", "Выбери номер", "Первая часть · №1–19", sections=(
        VisualSection("Практические задачи", tuple(VisualEntry(str(n)) for n in range(1, 6)),
                      layout="practical"),
        VisualSection("Алгебра и вероятность", (VisualEntry("Вычисления", key="6"),),
                      layout="tiles"),
        VisualSection("Геометрия", (
            VisualEntry("Четырёхугольники", key="17"),
            VisualEntry("Фигуры на клетчатой сетке", key="18"),
            VisualEntry("Геометрические утверждения", key="19"),
        ), layout="tiles"),
    ))
    image = _png(card)

    positions = {text: (x, y) for x, y, text in transcript}
    assert {str(n) for n in range(1, 6)} <= positions.keys()
    assert positions["Четырёхугольники"][0] == positions["Геометрические утверждения"][0]
    assert positions["Фигуры на"][0] > positions["Четырёхугольники"][0] + 200
    assert positions["Геометрические утверждения"][1] > positions["клетчатой"][1]
    assert image.getpixel((355 * 3, 140 * 3)) == (246, 221, 208)
    assert image.getpixel((370 * 3, (image.height // 3 - 25) * 3)) == (226, 236, 232)


def test_all_six_story_descriptions_and_long_type_rows_render(transcript):
    stories = (
        ("Шины", "TYRES", "Размеры колёс"), ("Бумага", "PAPER", "Форматы листов"),
        ("Печи", "STOVE", "Размеры и цены"), ("Тарифы", "TARIFF", "Минуты и оплата"),
        ("Участки", "GARDEN", "План участка"), ("Квартиры", "FLAT", "План квартиры"),
    )
    _png(VisualCard("stories", "Выбери сюжет", "Практические задачи · №5", sections=(
        VisualSection("", tuple(VisualEntry(name, icon=icon) for name, icon, _ in stories),
                      layout="tiles"),
    )))
    painted = " ".join(text for _, _, text in transcript)
    for name, _, description in stories:
        assert f"{name} {description}" in painted

    transcript.clear()
    title = "Нахождение площади поверхности и объёма прямоугольного параллелепипеда"
    _png(VisualCard("types", "Выбери тип", "№15", sections=(VisualSection("", (
        VisualEntry(title, key="12", detail="Закрепление · 2/3", value="100/149 верно"),
    )),)))
    assert title in " ".join(text for _, _, text in transcript)
    assert "Закрепление · 2/3" in {text for _, _, text in transcript}
    assert "100/149 верно" in " ".join(text for _, _, text in transcript)


def test_progress_shows_three_unequal_metric_columns_and_a_diagnostic(transcript):
    card = VisualCard("number_progress", "№6 · Прогресс", "Вычисления", metrics=(
        VisualMetric("1313 из 1818", "Решено верно"), VisualMetric("72%", "Успешность"),
        VisualMetric("710", "Новых самостоятельно", "good"),
    ), note="Выдано: 2000 · Пропущено: 182", hint="Вычитание обыкновенных дробей")
    image = _png(card)

    painted = " ".join(text for _, _, text in transcript)
    assert "1313 из 1818" in painted
    assert "Новых самостоятельно" in painted
    assert "Вычитание обыкновенных дробей" in painted
    assert image.getpixel((25 * 3, (image.height // 3 - 25) * 3)) == (248, 232, 200)


def test_result_legend_preserves_distinct_outcomes_and_layout_is_bounded(transcript):
    entries = tuple(VisualEntry(label, key=f"№{i}", tone=tone, icon=icon)
                    for i, (label, tone, icon) in enumerate((
                        ("Самостоятельно", "good", "independent"),
                        ("Со второй попытки", "good", "retry"),
                        ("С подсказкой", "good", "hint"),
                        ("Верно", "good", "correct"),
                        ("Неверно", "bad", "wrong"),
                        ("Пропущено", "muted", "skipped"),
                        ("Открыт разбор", "muted", "solution"),
                        ("Не завершено", "muted", "pending"),
                    ), 1))
    card = VisualCard("training_result", "Итог тренировки", sections=(
        VisualSection("По заданиям", entries, "outcomes"),
    ))
    _png(card)
    painted = {text for _, _, text in transcript}
    assert {entry.label for entry in entries} <= painted
    assert {entry.key for entry in entries} <= painted

    with pytest.raises(CardLayoutError, match="exceeds"):
        render_card(VisualCard("types", "Типы", sections=(
            VisualSection("", (VisualEntry("Уравнение"),) * 100),
        )))


@pytest.mark.parametrize(("title", "breakdown", "practice", "recommendation", "colors"), (
    ("Промежуточный итог", VisualBreakdown(3, 2, 0, 0),
     (VisualPractice("Медиана к гипотенузе по клеткам", 2, 3),), "",
     ((120, (37, 96, 67)), (310, (135, 165, 131)))),
    ("Промежуточный итог", VisualBreakdown(3, 0, 2, 0), (), "",
     ((120, (37, 96, 67)), (310, (144, 61, 52)))),
    ("Итог тренировки", VisualBreakdown(1, 0, 3, 1),
     (VisualPractice("Какой корень принадлежит отрезку", 1, 3),), "№19 · Прямые и углы",
     ((50, (37, 96, 67)), (180, (144, 61, 52)), (345, (128, 145, 138)))),
), ids=("checkpoint-practice", "checkpoint-no-change", "final-recommendation"))
def test_aggregate_summary_examples_at_mobile_widths(
    transcript, title, breakdown, practice, recommendation, colors,
):
    sections = ((VisualSection("Что повторить", (VisualEntry(recommendation),)),)
                if recommendation else ())
    card = VisualCard("training_result", title, "5 заданий", sections=sections,
                      breakdown=breakdown, practice=practice)
    image = _png(card)

    positions = {text: (x, y) for x, y, text in transcript}
    assert positions["Решено верно"] == (25, 163)
    assert positions["Самостоятельно"] == (209, 163)
    assert f"{breakdown.independent + breakdown.assisted} из 5" in positions
    assert f"{breakdown.independent} из 5" in positions
    assert f"{breakdown.skipped} · Пропущено" in positions
    assert f"{breakdown.assisted} · Другие верные" in positions
    assert "По заданиям" not in positions
    assert ("Закрепление типа" in positions) == bool(practice)
    assert ("Что повторить" in positions) == bool(recommendation)
    assert not {"Продолжить", "Мой прогресс", "В меню"} & positions.keys()
    painted = " ".join(text for _, _, text in transcript)

    for display_width in (360, 390, 430):
        ratio = display_width / 400
        display_height = round(image.height * display_width / image.width)
        display = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        assert display.height < 500
        for logical_x, color in colors:
            pixel = display.getpixel((round(logical_x * ratio), round(198 * ratio)))
            assert all(abs(actual - expected) < 6
                       for actual, expected in zip(pixel, color, strict=True))
        if practice:
            skill = practice[0]
            assert skill.status in painted
            dot_y = positions[skill.label][1] + 28
            active = display.getpixel((round(22 * ratio), round(dot_y * ratio)))
            empty = display.getpixel((round(58 * ratio), round(dot_y * ratio)))
            assert active[0] < 50
            assert empty[0] > 230


@pytest.mark.parametrize("breakdown", (
    VisualBreakdown(5, 0, 0, 0),
    VisualBreakdown(0, 0, 5, 0),
    VisualBreakdown(0, 0, 0, 0),
    VisualBreakdown(3, 0, 1, 0),
    VisualBreakdown(30, 20, 13, 2),
    VisualBreakdown(5, 7, 6, 1),
), ids=("perfect", "no-correct", "ended-before-issuance", "ended-early", "long", "first-part"))
def test_aggregate_only_summary_never_infers_an_outcome_order(transcript, breakdown):
    _png(VisualCard("training_result", "Итог тренировки", breakdown=breakdown))

    painted = {text for _, _, text in transcript}
    assert f"{breakdown.independent} из {breakdown.total}" in painted
    assert all(f"{count} · {label}" in painted for count, label in (
        (breakdown.independent, "Самостоятельно"), (breakdown.assisted, "Другие верные"),
        (breakdown.unsolved, "Не решено"), (breakdown.skipped, "Пропущено"),
    ))
    assert not {"По заданиям", "1", "№1", "Закрепление типа"} & painted


def test_practice_marks_only_a_confirmed_type_as_finished(transcript):
    card = VisualCard("training_result", "Итог тренировки", breakdown=VisualBreakdown(1, 0, 0, 0),
                      practice=(VisualPractice("Корни уравнения", 3, 3, confirmed=True),))
    _png(card)

    assert "Тип закреплён" in {text for _, _, text in transcript}
    assert all("Ещё 0" not in text for _, _, text in transcript)
