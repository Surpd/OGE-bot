import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import BufferedInputFile, Chat, Message
from PIL import Image

from app.bot.math_fragments import Comparison, Fraction, MathToken, System
from app.bot.math_image import _formula, render_math_image
from app.bot.math_notation import math_spans, parse_formula, rich_needs_png_fallback
from app.bot.presentation import format_rich_message, send_photo, send_text


@pytest.mark.parametrize(
    "source, expected",
    [
        ("−3/4", r"\frac{-3}{4}"),
        ("m·v²/2", r"\frac{m \cdot {v}^{2}}{2}"),
        ("aₙ = a₁ + (n − 1)d", r"a_{n} = a_{1} + \left(n - 1\right)d"),
        ("√(49)", r"\sqrt{\left(49\right)}"),
        ("(−2; 3]", r"\left(-2; 3\right]"),
        ("2^(-3)", r"{2}^{\left(-3\right)}"),
        ("y=1/(2x)", r"y = \frac{1}{\left(2x\right)}"),
        ("y=−3/(4x)", r"y = \frac{-3}{\left(4x\right)}"),
        ("y=(1/2)x", r"y = \left(\frac{1}{2}\right)x"),
    ],
)
def test_lossless_grammar_has_explicit_fraction_power_and_interval_scope(source, expected):
    assert parse_formula(source) == expected
    assert "".join(span.source for span in math_spans(source)) == source


@pytest.mark.parametrize("source", ["a/bc", "1 1/2", "x1", "√x²", "x^", "(1+2", r"\frac{1}{2}"])
def test_ambiguous_or_unknown_notation_is_not_inferred(source):
    assert parse_formula(source) is None
    assert "".join(span.source for span in math_spans(source)) == source


def test_rich_html_is_escaped_and_reaches_real_typesetting_image(tmp_path):
    source = "Задание №8 · Выражения\n\nВычислите (−3/4 + 1/2) : 0,5.\n√(49) = 7\nОтвет: −0,5"
    rich = format_rich_message(source)
    assert "<tg-math>" in rich
    assert r"\frac{-3}{4}" in rich
    assert "&lt;script&gt;" in format_rich_message("<script>")
    output = render_math_image(source)
    image = Image.open(io.BytesIO(output))
    assert image.format == "PNG" and image.width == 1200
    assert 150 < image.height < 6000
    assert image.getextrema()[0][0] < 100
    (tmp_path / "math.png").write_bytes(output)


@pytest.mark.parametrize(
    "source, expected_latex",
    [
        ("y=1/(2x)", r"y = \frac{1}{\left(2x\right)}"),
        ("y=−3/(4x)", r"y = \frac{-3}{\left(4x\right)}"),
        ("y=(1/2)x", r"y = \left(\frac{1}{2}\right)x"),
        ("y=3/(2(x+1))", r"y = \frac{3}{\left(2\left(x + 1\right)\right)}"),
    ],
)
def test_oge11_rational_formula_has_unambiguous_rich_and_png_rendering(
    source, expected_latex
):
    from fractions import Fraction as Rational

    from app.math.oge11 import Graph

    if source == "y=1/(2x)":
        for coefficient, generated in (
            (Rational(1, 2), "y=1/(2x)"),
            (Rational(-1, 2), "y=-1/(2x)"),
            (Rational(3, 2), "y=3/(2x)"),
        ):
            assert Graph("inverse", (coefficient,)).formula() == generated
            assert parse_formula(generated) is not None
    assert parse_formula(source) == expected_latex
    rich = format_rich_message("Задание №11\n" + source)
    assert expected_latex.replace("&", "&amp;") in rich
    image = Image.open(io.BytesIO(render_math_image(source)))
    assert image.format == "PNG" and image.width == 1200 and image.height > 60


def test_oge11_inverse_formula_keeps_the_generator_model_equivalent():
    from fractions import Fraction as Rational

    from app.math.oge11 import Graph, _parse_formula

    for coefficient in (Rational(1, 2), Rational(-3, 4), Rational(3, 2)):
        model = Graph("inverse", (coefficient,))
        visible_formula = model.formula()
        parsed_formula = _parse_formula(visible_formula)
        for x in (Rational(-3), Rational(-1, 2), Rational(1, 3), Rational(4)):
            assert parsed_formula.value(x) == model.value(x)


@pytest.mark.parametrize(
    "source, expected_latex",
    [
        ("2x", "2x"),
        ("3ab", "3ab"),
        ("5x²", r"5{x}^{2}"),
        ("xy", "xy"),
        ("2(x+3)", r"2\left(x + 3\right)"),
        ("1/(2x)", r"\frac{1}{\left(2x\right)}"),
        ("1/(3xy)", r"\frac{1}{\left(3xy\right)}"),
        ("aₙ = a₁ + (n − 1)d", r"a_{n} = a_{1} + \left(n - 1\right)d"),
        ("E=mv²/2", r"E = \frac{m{v}^{2}}{2}"),
        ("F=ma", "F = ma"),
        ("2×3", r"2 \times 3"),
    ],
)
def test_school_juxtaposition_matches_final_png_pixels(source, expected_latex):
    assert parse_formula(source) == expected_latex
    actual = Image.open(io.BytesIO(render_math_image(source))).convert("RGB")
    tile = _formula(expected_latex)
    expected = Image.new("RGB", tile.size, "white")
    expected.paste(tile, (0, 0), tile)
    assert actual.crop((48, 48, 48 + tile.width, 48 + tile.height)).tobytes() == expected.tobytes()


def test_rich_fallback_is_scoped_to_implicit_products_in_fraction_denominators():
    assert rich_needs_png_fallback("Задание №11\ny=1/(2x)")
    assert rich_needs_png_fallback("1/(3xy)")
    assert rich_needs_png_fallback("1/(2(x+3))")
    assert not rich_needs_png_fallback("2x + 3ab + 5x²")
    assert not rich_needs_png_fallback("1/(2·x)")
    assert not rich_needs_png_fallback("2×3")


@pytest.mark.parametrize(
    "interval",
    [
        "(−∞; −33,54] ∪ [0; +∞)",
        "(−∞; 0)",
        "[−2; +∞)",
        "(−∞; 3] ∪ (5; +∞)",
    ],
)
def test_oge13_interval_rich_and_png_outputs_show_each_infinity_once(interval):
    source = "Ответ: " + interval
    rich = format_rich_message(source)
    assert rich.count("∞") == interval.count("∞")
    assert r"\infty" not in rich
    assert "−∞" in rich or "+∞" in rich
    image = Image.open(io.BytesIO(render_math_image(source)))
    assert image.format == "PNG" and image.width == 1200 and image.height > 60


def test_oge13_option_list_keeps_interval_edges_and_decimal_comma_visible():
    from fractions import Fraction as Rational

    from app.math.inequalities import Interval, format_set

    answer = format_set(
        (Interval(None, Rational(-1677, 50), False, True),
         Interval(Rational(0), None, True, False))
    )
    assert answer == "(−∞;-33,54] ∪ [0;+∞)"
    rich = format_rich_message("Варианты ответа:\n1) " + answer)
    assert rich.count("∞") == 2
    assert r"\infty" not in rich
    assert "-33,54" in rich


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "Задание №11\ny=1/(2x)",
        "Ответ: (−∞; −33,54] ∪ [0; +∞)",
    ],
)
@pytest.mark.parametrize("display", ("auto", "png"))
async def test_reported_math_cases_use_final_rich_or_png_transport(source, display):
    bot = Bot("123456:TEST")
    sent = Message(message_id=96, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_rich_message = AsyncMock(return_value=sent)
    bot.send_photo = AsyncMock(return_value=sent)
    repository = AsyncMock()
    repository.math_display.return_value = display

    result = await send_text(incoming(bot), repository, source)

    assert result.message_id == 96
    unsafe_rational = "y=1/(2x)" in source
    if display == "auto" and not unsafe_rational:
        html = bot.send_rich_message.await_args.kwargs["rich_message"].html
        assert html.count("∞") == 2
        assert r"\infty" not in html
        bot.send_photo.assert_not_awaited()
    else:
        image = bot.send_photo.await_args.kwargs["photo"].data
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        decoded = Image.open(io.BytesIO(image))
        assert decoded.format == "PNG" and decoded.width == 1200
        bot.send_rich_message.assert_not_awaited()
    await bot.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    ["2x", "3ab", "5x²", "xy", "2(x+3)", "aₙ = a₁ + (n − 1)d", "E=mv²/2", "F=ma"],
)
async def test_school_juxtaposition_stays_in_rich_transport_without_dot(source):
    bot = Bot("123456:TEST")
    sent = Message(message_id=97, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_rich_message = AsyncMock(return_value=sent)
    bot.send_photo = AsyncMock()
    repository = AsyncMock()
    repository.math_display.return_value = "auto"

    result = await send_text(incoming(bot), repository, source)

    html = bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert result.message_id == 97
    assert r"\cdot" not in html
    bot.send_photo.assert_not_awaited()
    await bot.session.close()


@pytest.mark.asyncio
async def test_oge11_inverse_graph_caption_uses_targeted_png_fallback():
    from fractions import Fraction as Rational

    from app.math.oge11 import Graph
    from app.math.oge11_render import render_graphs

    bot = Bot("123456:TEST")
    sent = Message(message_id=98, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_rich_message = AsyncMock()
    bot.send_photo = AsyncMock(return_value=sent)
    repository = AsyncMock()
    repository.math_display.return_value = "auto"
    graph_png, _ = render_graphs(
        (
            Graph("inverse", (Rational(1, 2),)),
            Graph("linear", (Rational(1), Rational(0))),
            Graph("quadratic", (Rational(1), Rational(0), Rational(0))),
        ),
        (0, 1, 2),
        "OGE11-F08",
        "test",
        (Rational(-10), Rational(10), Rational(-10), Rational(10)),
    )
    caption = "Задание №11\nФункция задана формулой y=1/(2x)."

    result = await send_photo(
        incoming(bot),
        repository,
        BufferedInputFile(graph_png, filename="oge11.png"),
        caption=caption,
    )

    assert result.message_id == 98
    bot.send_rich_message.assert_not_awaited()
    upload = bot.send_photo.await_args.kwargs["photo"]
    image = Image.open(io.BytesIO(upload.data))
    assert image.format == "PNG" and image.width == 1200 and image.height > 300
    await bot.session.close()


def test_typed_system_is_native_latex_and_image_rows_are_not_reparsed():
    system = System(
        (
            Comparison(MathToken("x"), ">", Fraction(MathToken("1"), MathToken("2"))),
            Comparison(MathToken("x"), "≤", MathToken("3")),
        )
    )
    assert r"\begin{cases}" in format_rich_message(system)
    output = render_math_image(system)
    assert Image.open(io.BytesIO(output)).height > 200
    condition = "Задание №13\nx > 1\nx ≤ 3"
    rows = ("x > 1", "x ≤ 3")
    assert r"\begin{cases}" in format_rich_message(condition, system_rows=rows)
    assert Image.open(io.BytesIO(render_math_image(condition, system_rows=rows))).height > 200


def test_owned_learning_layout_numbers_hints_steps_and_separates_final_answer():
    from app.bot.presentation import hint_message

    assert hint_message("Второй совет", {"hints": ["Первый совет", "Второй совет"]}).startswith(
        "Подсказка №2:"
    )
    source = "Вторая попытка неверна. Ответ: 1/2\n\nРазбор:\nВыразим: x = 1/2"
    rich = format_rich_message(source)
    assert "<b>1. Выразим:</b>" in rich
    assert rich.endswith(r"<p><b>Ответ:</b> <tg-math>\frac{1}{2}</tg-math></p>")
    assert source.startswith("Вторая попытка неверна. Ответ: 1/2")


@pytest.mark.asyncio
async def test_inline_navigation_proxy_still_uses_rich_condition_transport():
    from types import SimpleNamespace

    from aiogram.types import User

    from app.bot.navigation import NavigationMessage

    bot = Bot("123456:TEST")
    sent = Message(message_id=94, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_rich_message = AsyncMock(return_value=sent)
    callback = SimpleNamespace(from_user=User(id=42, is_bot=False, first_name="Student"))
    repository = AsyncMock()
    proxy = NavigationMessage(incoming(bot), callback, repository)
    result = await send_text(proxy, repository, "Задание №6\n1/2 + 1/4")
    assert result.message_id == 94
    bot.send_rich_message.assert_awaited_once()
    await bot.session.close()


@pytest.mark.asyncio
async def test_user_png_choice_works_when_client_capability_is_not_exposed():
    bot = Bot("123456:TEST")
    bot.send_rich_message = AsyncMock()
    sent = Message(message_id=95, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_photo = AsyncMock(return_value=sent)
    repository = AsyncMock()
    repository.math_display.return_value = "png"
    assert (await send_text(incoming(bot), repository, "Ответ: 1/2")).message_id == 95
    repository.math_display.assert_awaited_once_with(42)
    bot.send_rich_message.assert_not_awaited()
    bot.send_photo.assert_awaited_once()
    await bot.session.close()


def incoming(bot):
    return Message(message_id=19, date=datetime.now(UTC), chat=Chat(id=42, type="private")).as_(bot)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_photo", [False, True])
async def test_native_rich_transport_preserves_message_id_controls_and_media(with_photo):
    bot = Bot("123456:TEST")
    sent = Message(message_id=91, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_rich_message = AsyncMock(return_value=sent)
    bot.send_photo = AsyncMock()
    repository = AsyncMock()
    message = incoming(bot)
    if with_photo:
        result = await send_photo(
            message,
            repository,
            BufferedInputFile(b"diagram", "figure.png"),
            caption="Задание №11\ny = 2x + 1",
        )
    else:
        result = await send_text(message, repository, "Задание №6\n1/2 + 1/4")
    assert result.message_id == 91
    payload = bot.send_rich_message.await_args.kwargs
    assert payload["chat_id"] == 42
    assert "<tg-math-block>" in payload["rich_message"].html
    if with_photo:
        assert payload["rich_message"].media[0].media.media.data == b"diagram"
        assert 'src="tg://photo?id=diagram"' in payload["rich_message"].html
    bot.send_photo.assert_not_awaited()
    repository.task6_answer.assert_not_awaited()
    await bot.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, fallback", [(TelegramBadRequest, True), (TelegramNetworkError, False)]
)
async def test_only_definite_rich_rejection_falls_back_without_rescoring(error, fallback):
    bot = Bot("123456:TEST")
    method = SendRichMessage(chat_id=42, rich_message={"html": "test"})
    bot.send_rich_message = AsyncMock(side_effect=error(method=method, message="unavailable"))
    sent = Message(message_id=92, date=datetime.now(UTC), chat=Chat(id=42, type="private"))
    bot.send_photo = AsyncMock(return_value=sent)
    repository = AsyncMock()
    if fallback:
        result = await send_text(incoming(bot), repository, "Ответ: 1/2")
        assert result.message_id == 92
        photo = bot.send_photo.await_args.kwargs["photo"]
        assert photo.data.startswith(b"\x89PNG")
        bot.send_photo.assert_awaited_once()
    else:
        with pytest.raises(TelegramNetworkError):
            await send_text(incoming(bot), repository, "Ответ: 1/2")
        bot.send_photo.assert_not_awaited()
    repository.task6_answer.assert_not_awaited()
    await bot.session.close()
