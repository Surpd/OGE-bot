"""Source-constrained generator for the connected OGE 1–5 tariff block.

Only the compatible set represented by Reshu OGE variant 71946582 is
implemented here. Research-only and blocked constructions remain unavailable.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from html import escape
from math import isclose
from random import Random
from typing import cast
from xml.etree import ElementTree

from app.math.scenario_engine import (
    AnswerPolicy,
    FamilyRegistration,
    FamilyStatus,
    IndependentOracle,
    JsonValue,
    QuestionBuilder,
    QuestionDraft,
    RenderedScenario,
    Renderer,
    ScenarioAssetRef,
    ScenarioDraft,
    ScenarioGenerator,
    ScenarioSnapshot,
    StoryAdapter,
)

GENERATOR_VERSION = "tariff-v1"
MATRIX_VERSION = "tariff-compatible-71946582-v1"
WORLD_VERSION = "tariff-world-v1"
MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
MINUTES_FAMILY = "TARIFF-F01-MONTHS-MINUTES"
BILL_FAMILY = "TARIFF-F04-MONTHLY-BILL"
MINIMUM_FAMILY = "TARIFF-F05-EXTREMUM"
PERCENT_FAMILY = "TARIFF-F09-PERCENT-FEE"
ISP_FAMILY = "TARIFF-F12-HOME-ISP"
COUNT_BASE_FAMILY = "TARIFF-F08-COUNT-BASE-PRICE"
SET_A = "71946582-A"

FAMILY_SOURCES: Mapping[str, tuple[str, ...]] = {
    MINUTES_FAMILY: ("442722", "461831"),
    BILL_FAMILY: ("461832",),
    MINIMUM_FAMILY: ("461833",),
    COUNT_BASE_FAMILY: ("441667",),
    PERCENT_FAMILY: ("461834",),
    ISP_FAMILY: ("461835",),
}
IMPLEMENTED_FAMILIES = (MINUTES_FAMILY, BILL_FAMILY, MINIMUM_FAMILY, PERCENT_FAMILY, ISP_FAMILY)
SET_A_SOURCES: Mapping[str, tuple[str, ...]] = {
    MINUTES_FAMILY: ("461831",),
    BILL_FAMILY: ("461832",),
    MINIMUM_FAMILY: ("461833",),
    PERCENT_FAMILY: ("461834",),
    ISP_FAMILY: ("461835",),
}
DISABLED_FAMILIES = (
    ("TARIFF-F02-MONTHS-GB", 1, FamilyStatus.ENABLED_CANDIDATE, ("406563",)),
    ("TARIFF-F03-TRENDS", 3, FamilyStatus.ENABLED_CANDIDATE, ("406675", "406676")),
    ("TARIFF-F06-COUNT-ONE-LIMIT", 3, FamilyStatus.ENABLED_CANDIDATE, ("408888",)),
    ("TARIFF-F07-COUNT-BOTH-LIMITS", 3, FamilyStatus.RESEARCH_ONLY, ("408888",)),
    (COUNT_BASE_FAMILY, 3, FamilyStatus.ENABLED_CANDIDATE, ("441667",)),
    ("TARIFF-F10-PERCENT-TRAFFIC", 4, FamilyStatus.RESEARCH_ONLY, ("461834",)),
    ("TARIFF-F11-ANNUAL-SWITCH", 5, FamilyStatus.ENABLED_CANDIDATE, ("442828",)),
    ("TARIFF-F13-SMARTPHONE-CREDIT", 5, FamilyStatus.ENABLED_CANDIDATE, ("449788",)),
    ("TARIFF-F14-LEGACY-STANDALONE", 5, FamilyStatus.BLOCKED, ("367106", "367110")),
    ("TARIFF-F15-SMS-MONTHLY-OVERAGE", 2, FamilyStatus.RESEARCH_ONLY, ("461832",)),
)


def _rubles(cents: int) -> str:
    if cents < 0:
        raise ValueError("Tariff cost cannot be negative")
    whole, remainder = divmod(cents, 100)
    return str(whole) if remainder == 0 else f"{whole},{remainder:02d}".rstrip("0")


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a tariff quantity")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    raise ValueError("Tariff quantity must be an integer")


def _parse_rubles(value: str) -> int:
    normalized = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", normalized):
        raise ValueError("Visible money must be a non-negative amount with at most two decimals")
    whole, _, fraction = normalized.partition(".")
    return _as_int(whole) * 100 + _as_int((fraction + "00")[:2])


def _ceil_packages(excess_quarters: int, pack_quarters: int) -> int:
    if excess_quarters <= 0:
        return 0
    if pack_quarters <= 0:
        raise ValueError("Data pack size must be positive")
    return (excess_quarters + pack_quarters - 1) // pack_quarters


def _monthly_bill_cents(context: Mapping[str, object], month_index: int) -> int:
    minutes = context["minutes"]
    gb_quarters = context["gb_quarters"]
    tariff = context["tariff"]
    if (
        not isinstance(minutes, tuple | list)
        or not isinstance(gb_quarters, tuple | list)
        or not isinstance(tariff, Mapping)
    ):
        raise ValueError("Invalid tariff world")
    included_minutes = _as_int(tariff["included_minutes"])
    included_gb_quarters = _as_int(tariff["included_gb_quarters"])
    included_sms = _as_int(tariff["included_sms_month"])
    annual_sms = _as_int(tariff["annual_sms"])
    if annual_sms > included_sms:
        raise ValueError("Annual-only SMS cannot determine a monthly overage")
    voice_excess = max(0, _as_int(minutes[month_index]) - included_minutes)
    data_packs = _ceil_packages(
        max(0, _as_int(gb_quarters[month_index]) - included_gb_quarters),
        _as_int(tariff["data_pack_quarters"]),
    )
    return (
        _as_int(tariff["monthly_fee_cents"])
        + voice_excess * _as_int(tariff["extra_minute_cents"])
        + data_packs * _as_int(tariff["data_pack_price_cents"])
    )


def _isp_costs_cents(isp: Mapping[str, object], usage_mb: int) -> tuple[int, ...]:
    plans = isp["plans"]
    if not isinstance(plans, tuple | list):
        raise ValueError("Invalid internet plans")
    costs: list[int] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            raise ValueError("Invalid internet plan")
        cost = _as_int(plan["monthly_fee_cents"])
        overage = max(0, usage_mb - _as_int(plan["included_mb"]))
        cost += overage * _as_int(plan["per_mb_cents"])
        costs.append(cost)
    return tuple(costs)


def _rubles_fraction(value: str) -> int:
    amount = Fraction(value.replace(",", ".")) * 100
    if amount.denominator != 1:
        raise ValueError("Displayed currency must resolve to whole kopecks")
    return amount.numerator


def _gb_quarters(value: str) -> int:
    amount = Fraction(value.replace(",", ".")) * 4
    if amount.denominator != 1:
        raise ValueError("Displayed GB amount must be on a quarter-GB boundary")
    return amount.numerator


class TariffGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        rng = Random(seed ^ 0x544152494646)
        compatible_set_id = SET_A
        # The researched scales allow 17 distinct values per graph series.
        minutes = rng.sample(list(range(0, 401, 25)), 12)
        gb_quarters = rng.sample(list(range(17)), 12)
        old_fee_cents = 35_000
        increase_percent = rng.choice((10, 20, 40, 50))
        new_fee_cents = old_fee_cents * (100 + increase_percent) // 100
        usage_mb = 10 * rng.randint(30, 120)
        plans = [
            {"name": "Поминутный", "monthly_fee_cents": 0, "included_mb": 0, "per_mb_cents": 150},
            {
                "name": "Домашний-200",
                "monthly_fee_cents": 20_400,
                "included_mb": 200,
                "per_mb_cents": 120,
            },
            {
                "name": "Домашний-700",
                "monthly_fee_cents": 67_200,
                "included_mb": 700,
                "per_mb_cents": 0,
            },
        ]
        isp: dict[str, object] = {"usage_mb": usage_mb, "plans": plans}
        costs = _isp_costs_cents(isp, usage_mb)
        # Exclude ties as the examined source has one uniquely cheapest plan.
        if costs.count(min(costs)) != 1:
            for usage_mb in range(300, 1201, 10):
                costs = _isp_costs_cents(isp, usage_mb)
                if costs.count(min(costs)) == 1:
                    isp["usage_mb"] = usage_mb
                    break
            else:
                raise ValueError("No unambiguous internet plan in the supported range")
        context: dict[str, object] = {
            "world_version": WORLD_VERSION,
            "compatible_set_id": compatible_set_id,
            "minutes": minutes,
            "gb_quarters": gb_quarters,
            "tariff": {
                "name": "Стандартный",
                "monthly_fee_cents": old_fee_cents,
                "included_minutes": 300,
                "included_gb_quarters": 12,
                "included_sms_month": 120,
                "annual_sms": 110,
                "extra_minute_cents": 300,
                "data_pack_quarters": 2,
                "data_pack_price_cents": 9_000,
                "fee_after_increase_cents": new_fee_cents,
                "increase_percent": increase_percent,
                "fee_change_kind": "increase",
            },
            "isp": isp,
        }
        return ScenarioDraft(
            "TARIFF",
            seed,
            GENERATOR_VERSION,
            cast(Mapping[str, JsonValue], context),
            MATRIX_VERSION,
            tuple(
                f"https://math-oge.sdamgia.ru/problem?id={task_id}"
                for task_id in ("461831", "461832", "461833", "461834", "461835")
            ),
        )


class TariffRenderer:
    def __init__(self) -> None:
        self._asset_cache: dict[tuple[int, str], bytes] = {}

    @staticmethod
    def _chart_svg(context: Mapping[str, object]) -> bytes:
        minutes = context["minutes"]
        gb_quarters = context["gb_quarters"]
        if not isinstance(minutes, tuple | list) or not isinstance(gb_quarters, tuple | list):
            raise ValueError("Invalid graph series")
        width, height = 900, 470
        left, right, top, bottom = 88, 830, 78, 390
        x_step = (right - left) / 11
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="836" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',  # noqa: E501
            '<title id="title">Расход минут и мобильного интернета за 12 месяцев</title>',
            '<desc id="desc">Сплошная линия — минуты слева, пунктирная — гигабайты справа. Месяцы подписаны по порядку.</desc>',  # noqa: E501
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            '<g font-family="Arial, sans-serif" fill="#172033">',
            '<text x="450" y="40" text-anchor="middle" font-size="32" font-weight="700">Расход минут и ГБ по месяцам</text>',  # noqa: E501
        ]
        for tick in range(0, 401, 50):
            y = bottom - (bottom - top) * tick / 400
            lines.append(f'<path d="M {left} {y:.2f} H {right}" stroke="#d9dee8"/>')
            lines.append(
                f'<text x="{left - 12}" y="{y + 8:.2f}" text-anchor="end" font-size="25">{tick}</text>'  # noqa: E501
            )
        for tick in range(0, 9):
            value = tick / 2
            y = bottom - (bottom - top) * value / 4
            label = f"{value:g}".replace(".", ",")
            lines.append(
                f'<text x="{right + 13}" y="{y + 8:.2f}" font-size="25">{label}</text>'
            )
        lines.extend(
            [
                f'<path d="M {left} {top} V {bottom} H {right}" fill="none" stroke="#24324a" stroke-width="2"/>',  # noqa: E501
                f'<path d="M {right} {top} V {bottom}" fill="none" stroke="#24324a" stroke-width="2"/>',  # noqa: E501
                f'<text x="20" y="{(top + bottom) / 2:.0f}" transform="rotate(-90 20 {(top + bottom) / 2:.0f})" text-anchor="middle" font-size="25">Минуты</text>',  # noqa: E501
                f'<text x="880" y="{(top + bottom) / 2:.0f}" transform="rotate(90 880 {(top + bottom) / 2:.0f})" text-anchor="middle" font-size="25">ГБ</text>',  # noqa: E501
            ]
        )
        min_points: list[str] = []
        gb_points: list[str] = []
        for i, month in enumerate(MONTHS):
            x = left + x_step * i
            y_min = bottom - (bottom - top) * _as_int(minutes[i]) / 400
            y_gb = bottom - (bottom - top) * (_as_int(gb_quarters[i]) / 4) / 4
            min_points.append(f"{x:.2f},{y_min:.2f}")
            gb_points.append(f"{x:.2f},{y_gb:.2f}")
            # Short labels alternate with full month names for mobile legibility.
            label = month[:3] + "."
            lines.append(
                f'<text x="{x:.2f}" y="{bottom + 34}" text-anchor="middle" font-size="25">{label}</text>'  # noqa: E501
            )
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y_min:.2f}" r="7" fill="#2463eb" aria-label="{month}: {minutes[i]} минут"/>'  # noqa: E501
            )
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y_gb:.2f}" r="7" fill="#d04a35" aria-label="{month}: {_as_int(gb_quarters[i]) / 4:g} ГБ"/>'  # noqa: E501
            )
        lines.append(
            f'<polyline points="{" ".join(min_points)}" fill="none" stroke="#2463eb" stroke-width="6"/>'  # noqa: E501
        )
        lines.append(
            f'<polyline points="{" ".join(gb_points)}" fill="none" stroke="#d04a35" stroke-width="6" stroke-dasharray="18 12"/>'  # noqa: E501
        )
        lines.extend(
            [
                '<path d="M 280 445 h 48" stroke="#2463eb" stroke-width="6"/><text x="338" y="453" font-size="24">минуты</text>',  # noqa: E501
                '<path d="M 500 445 h 48" stroke="#d04a35" stroke-width="6" stroke-dasharray="18 12"/><text x="558" y="453" font-size="24">интернет, ГБ</text>',  # noqa: E501
                "</g></svg>",
            ]
        )
        return "".join(lines).encode("utf-8")

    @staticmethod
    def _table_svg(context: Mapping[str, object]) -> bytes:
        isp = context["isp"]
        if not isinstance(isp, Mapping) or not isinstance(isp["plans"], tuple | list):
            raise ValueError("Invalid ISP table")
        width, height = 760, 235
        rows = [
            ["План", "Абонплата", "Включено", "Сверх пакета"],
            ["Поминутный", "нет", "нет", "1,50 руб./МБ"],
            ["Домашний-200", "204 руб./мес.", "200 МБ", "1,20 руб./МБ"],
            ["Домашний-700", "672 руб./мес.", "700 МБ", "нет"],
        ]
        x = (22, 250, 430, 570)
        y0, row_h = 34, 47
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="495" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">',  # noqa: E501
            '<title id="title">Тарифы домашнего интернета</title>',
            '<rect width="100%" height="100%" fill="#fff"/>',
            '<g font-family="Arial, sans-serif" fill="#172033">',
        ]
        for ri, row in enumerate(rows):
            y = y0 + ri * row_h
            if ri == 0:
                parts.append(
                    f'<rect x="12" y="{y - 26}" width="736" height="40" rx="4" fill="#e9eef8"/>'
                )
            parts.append(f'<path d="M 12 {y + 17} H 748" stroke="#ccd3df"/>')
            for ci, value in enumerate(row):
                parts.append(
                    f'<text x="{x[ci]}" y="{y}" font-size="25" font-weight="{700 if ri == 0 else 400}">{escape(value)}</text>'  # noqa: E501
                )
        parts.append("</g></svg>")
        return "".join(parts).encode("utf-8")

    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        context = cast(Mapping[str, object], scenario.context)
        tariff = context["tariff"]
        if not isinstance(tariff, Mapping):
            raise ValueError("Invalid tariff context")
        minutes = context["minutes"]
        gb = context["gb_quarters"]
        if not isinstance(minutes, tuple | list) or not isinstance(gb, tuple | list):
            raise ValueError("Invalid scenario series")
        shared = (
            "За каждый месяц года показаны расход минут исходящих вызовов и мобильного интернета.\n"
            "На графике сплошная линия — минуты (левая шкала), пунктирная — интернет в ГБ (правая шкала).\n"  # noqa: E501
            f"Тариф «{tariff['name']}»: абонентская плата {_rubles(_as_int(tariff['monthly_fee_cents']))} руб./мес.; "  # noqa: E501
            f"включено {tariff['included_minutes']} минут, {_as_int(tariff['included_gb_quarters']) / 4:g} ГБ и {tariff['included_sms_month']} SMS в месяц.\n"  # noqa: E501
            f"Сверх пакета: {_as_int(tariff['extra_minute_cents']) / 100:g} руб./мин.; интернет — "
            f"{_rubles(_as_int(tariff['data_pack_price_cents']))} руб. за {_as_int(tariff['data_pack_quarters']) / 4:g} ГБ. "  # noqa: E501
            f"За год отправлено {tariff['annual_sms']} SMS.\n"
            "Таблица вариантов домашнего интернета приведена в задании №5.\n"
            f"Минуты по месяцам: {', '.join(str(v) for v in minutes)}.\n"
            f"Мобильный интернет по месяцам: {', '.join(f'{_as_int(v) / 4:g}' for v in gb)} ГБ.\n"
            "Месяцы указаны в календарном порядке с января по декабрь."
        )
        assets: list[ScenarioAssetRef] = []
        for name, content_type, content in (
            ("usage-chart", "image/svg+xml", self._chart_svg(context)),
            ("home-internet-table", "image/svg+xml", self._table_svg(context)),
        ):
            digest = sha256(content).hexdigest()
            self._asset_cache[(scenario.seed, name)] = content
            assets.append(ScenarioAssetRef(digest, content_type, f"sha256/{digest}.svg"))
        return RenderedScenario(shared, tuple(assets))

    def asset_bytes(self, scenario: ScenarioDraft, name: str) -> bytes:
        return self._asset_cache.get((scenario.seed, name), b"")

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        context = snapshot.context
        rendered = self.render_scenario(
            ScenarioDraft(
                snapshot.story_code,
                snapshot.seed,
                snapshot.generator_version,
                context,
                snapshot.compatibility_matrix_version,
                snapshot.provenance,
            )
        )
        for ref, name in zip(rendered.assets, ("usage-chart", "home-internet-table"), strict=True):
            if ref == asset:
                return self.asset_bytes(
                    ScenarioDraft(
                        snapshot.story_code,
                        snapshot.seed,
                        snapshot.generator_version,
                        context,
                        snapshot.compatibility_matrix_version,
                        snapshot.provenance,
                    ),
                    name,
                )
        raise ValueError("Unknown TARIFF asset")


class TariffQuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        context = cast(Mapping[str, object], scenario.context)
        tariff = context["tariff"]
        if not isinstance(tariff, Mapping):
            raise ValueError("Invalid tariff context")
        minutes = context["minutes"]
        gb_quarters = context["gb_quarters"]
        if not isinstance(minutes, tuple | list) or not isinstance(gb_quarters, tuple | list):
            raise ValueError("Invalid scenario series")
        rng = Random(scenario.seed ^ (0x15A0 + position))
        if position == 1:
            family, source = MINUTES_FAMILY, FAMILY_SOURCES[MINUTES_FAMILY]
            values = minutes
            indexes = rng.sample(range(12), 4)
            rng.shuffle(indexes)
            targets = [_as_int(values[i]) for i in indexes]
            answer = "".join(str(i + 1) for i in indexes)
            condition = (
                "Определите номера месяцев, в которых израсходовано соответственно "
                + ", ".join(f"{value} мин" for value in targets)
                + ". Запишите номера подряд, без разделителей."
            )
            hints = (
                "На графике выберите сплошную линию и левую шкалу минут.",
                "Для каждого значения найдите месяц; сохраняйте порядок значений в условии.",
            )
            steps = tuple(
                f"{value} мин — {MONTHS[index]} ({index + 1})."
                for value, index in zip(targets, indexes, strict=True)
            ) + (f"В указанном порядке получаем код {answer}.",)
            model: dict[str, JsonValue] = {"targets_minutes": tuple(targets)}
        elif position == 2:
            family, source = BILL_FAMILY, FAMILY_SOURCES[BILL_FAMILY]
            month_index = rng.randrange(12)
            bill = _monthly_bill_cents(context, month_index)
            answer = _rubles(bill)
            condition = f"Определите плату за услуги связи за {MONTHS[month_index]} при расходе, показанном на графике. Ответ укажите в рублях."  # noqa: E501
            voice = max(0, _as_int(minutes[month_index]) - _as_int(tariff["included_minutes"]))
            packs = _ceil_packages(
                max(
                    0,
                    _as_int(gb_quarters[month_index]) - _as_int(tariff["included_gb_quarters"]),
                ),
                _as_int(tariff["data_pack_quarters"]),
            )
            hints = (
                "Сначала найдите расход минут и ГБ за указанный месяц.",
                "Абонплата уже включает пакеты; отдельно посчитайте только превышения. Неполный пакет интернета оплачивается целиком.",  # noqa: E501
            )
            steps = (
                f"Абонплата: {_rubles(_as_int(tariff['monthly_fee_cents']))} руб.",
                f"Минуты сверх пакета: {voice}; доплата {_rubles(voice * _as_int(tariff['extra_minute_cents']))} руб.",  # noqa: E501
                f"Пакетов интернета сверх лимита: {packs}; доплата {_rubles(packs * _as_int(tariff['data_pack_price_cents']))} руб.",  # noqa: E501
                f"Итого: {_rubles(bill)} руб.",
            )
            model = {"month_index": month_index}
        elif position == 3:
            family, _, source = MINIMUM_FAMILY, "integer", FAMILY_SOURCES[MINIMUM_FAMILY]
            values = minutes
            answer = str(min(_as_int(value) for value in values))
            condition = (
                "Определите наименьшее количество минут исходящих вызовов за один месяц по графику."
            )
            month_index = next(
                i for i, value in enumerate(values) if _as_int(value) == _as_int(answer)
            )
            hints = (
                "Используйте сплошную линию и левую шкалу.",
                "Сравните значения для всех двенадцати месяцев и выберите минимальное.",
            )
            steps = (
                f"Наименьшая точка ряда минут соответствует {MONTHS[month_index]}.",
                f"Минимальный расход равен {answer} мин.",
            )
            model = {"series": "minutes"}
        elif position == 4:
            family, _, source = PERCENT_FAMILY, "integer", FAMILY_SOURCES[PERCENT_FAMILY]
            old_fee = _as_int(tariff["monthly_fee_cents"])
            new_fee = _as_int(tariff["fee_after_increase_cents"])
            numerator = (new_fee - old_fee) * 100
            if numerator % old_fee:
                raise ValueError("Generated fee increase is not an exact whole percent")
            answer = str(numerator // old_fee)
            condition = f"Абонентская плата выросла с {_rubles(old_fee)} руб. до {_rubles(new_fee)} руб. На сколько процентов она увеличилась?"  # noqa: E501
            hints = (
                "Процент увеличения считают от первоначальной платы.",
                "Вычтите старую плату из новой и разделите разность на старую плату.",
            )
            steps = (
                f"Изменение платы: {_rubles(new_fee - old_fee)} руб.",
                f"{_rubles(new_fee - old_fee)} / {_rubles(old_fee)} × 100 = {answer}%.",
            )
            model = {"fee_change_kind": "increase"}
        elif position == 5:
            family, _, source = ISP_FAMILY, "integer_rubles", FAMILY_SOURCES[ISP_FAMILY]
            isp = context["isp"]
            if not isinstance(isp, Mapping):
                raise ValueError("Invalid ISP data")
            usage = _as_int(isp["usage_mb"])
            costs = _isp_costs_cents(isp, usage)
            if costs.count(min(costs)) != 1:
                raise ValueError("Cheapest internet plan is not unique")
            answer = _rubles(min(costs))
            condition = f"Месячный расход домашнего интернета составляет {usage} МБ. Используйте тарифы в таблице и определите наименьшую плату за месяц. Ответ укажите в рублях."  # noqa: E501
            hints = (
                "Для каждого плана учтите включённый объём и абонплату.",
                "Плату за объём сверх лимита добавляйте только к абонплате этого плана.",
            )
            plans = isp["plans"]
            if not isinstance(plans, tuple | list):
                raise ValueError("Invalid ISP plans")
            plan_steps: list[str] = []
            for item, cost in zip(plans, costs, strict=True):
                if not isinstance(item, Mapping):
                    raise ValueError("Invalid ISP plan")
                plan_steps.append(f"{item['name']}: {_rubles(cost)} руб.")
            steps = tuple(plan_steps) + (f"Наименьшая плата — {_rubles(min(costs))} руб.",)
            model = {"usage_mb": usage}
        else:
            raise ValueError("TARIFF questions are numbered 1 through 5")
        policy_id = f"tariff.{family.lower()}"
        return QuestionDraft(
            position,
            scenario.seed,
            family,
            GENERATOR_VERSION,
            condition,
            policy_id,
            "1",
            answer,
            hints,
            steps,
            cast(Mapping[str, JsonValue], {**model, "source_ids": tuple(source)}),
        )


@dataclass(frozen=True, slots=True)
class TariffAnswerPolicy:
    policy_id: str
    version: str = "1"

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        normalized = raw_answer.strip().replace("\u00a0", "").replace(" ", "")
        if self.policy_id.endswith("months-minutes"):
            return bool(re.fullmatch(r"\d{4,8}", normalized)) and normalized == canonical_answer
        if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", normalized):
            return False
        try:
            return _rubles(_parse_rubles(normalized)) == canonical_answer
        except ValueError:
            return False


class TariffOracle:
    def __init__(self, renderer: TariffRenderer) -> None:
        self.renderer = renderer

    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        if scenario.story_code != "TARIFF" or scenario.generator_version != GENERATOR_VERSION:
            raise ValueError("Unexpected TARIFF scenario version")
        context = cast(Mapping[str, object], scenario.context)
        if context.get("compatible_set_id") != SET_A:
            raise ValueError("Only source-verified compatible set 71946582 is supported")
        minutes, gb = context.get("minutes"), context.get("gb_quarters")
        tariff = context.get("tariff")
        if (
            not isinstance(minutes, tuple | list)
            or not isinstance(gb, tuple | list)
            or len(minutes) != 12
            or len(gb) != 12
        ):
            raise ValueError("The visible graph must contain exactly twelve months")
        if any(not 0 <= _as_int(value) <= 400 or _as_int(value) % 25 for value in minutes):
            raise ValueError("Minute series violates the displayed 0–400 scale or 25-minute step")
        if any(not 0 <= _as_int(value) <= 16 for value in gb):
            raise ValueError("Internet series violates the displayed 0–4 GB scale")
        if not isinstance(tariff, Mapping):
            raise ValueError("Tariff table is missing")
        if (
            _as_int(tariff["monthly_fee_cents"]) < 0
            or _as_int(tariff["extra_minute_cents"]) < 0
            or _as_int(tariff["data_pack_price_cents"]) < 0
        ):
            raise ValueError("Tariff costs cannot be negative")
        if _as_int(tariff["included_minutes"]) < 0 or _as_int(tariff["included_gb_quarters"]) < 0:
            raise ValueError("Included tariff limits cannot be negative")
        if _as_int(tariff["data_pack_quarters"]) <= 0 or _as_int(tariff["included_sms_month"]) < 0:
            raise ValueError("Tariff units and limits must be valid")
        if _as_int(tariff["annual_sms"]) > _as_int(tariff["included_sms_month"]):
            raise ValueError("Annual SMS total does not prove zero monthly overage")
        if Counter(_as_int(value) for value in minutes).most_common(1)[0][1] != 1:
            raise ValueError("The selected minute values would not be uniquely identifiable")
        isp = context.get("isp")
        if not isinstance(isp, Mapping):
            raise ValueError("Home internet table is missing")
        usage = _as_int(isp["usage_mb"])
        plans = isp["plans"]
        if not isinstance(plans, tuple | list) or usage <= 0 or len(plans) != 3:
            raise ValueError("Invalid home internet table")
        for plan in plans:
            if (
                not isinstance(plan, Mapping)
                or min(
                    _as_int(plan[k]) for k in ("monthly_fee_cents", "included_mb", "per_mb_cents")
                )
                < 0
            ):
                raise ValueError("Home internet prices and limits cannot be negative")
        costs = _isp_costs_cents(isp, usage)
        if costs.count(min(costs)) != 1:
            raise ValueError("Home internet offers must have a unique cheapest option")

    def _visible_series(
        self, scenario: ScenarioDraft, rendered: RenderedScenario
    ) -> tuple[list[int], list[int]]:
        context = cast(Mapping[str, object], scenario.context)
        expected_minutes = context["minutes"]
        expected_gb = context["gb_quarters"]
        if not isinstance(expected_minutes, tuple | list) or not isinstance(
            expected_gb, tuple | list
        ):
            raise ValueError("Scenario series are missing")
        graph = next(
            (
                a
                for a in rendered.assets
                if a.content_type == "image/svg+xml"
                and a.storage_key
                == f"sha256/{sha256(self.renderer.asset_bytes(scenario, 'usage-chart')).hexdigest()}.svg"  # noqa: E501
            ),
            None,
        )
        if graph is None:
            raise ValueError("Visible chart asset is missing from rendered context")
        root = ElementTree.fromstring(self.renderer.asset_bytes(scenario, "usage-chart"))
        ns = {"s": "http://www.w3.org/2000/svg"}
        minute_ticks: dict[float, int] = {}
        gb_ticks: dict[float, int] = {}
        for node in root.findall(".//s:text", ns):
            text_value = (node.text or "").strip()
            x = float(node.attrib.get("x", "nan"))
            y = float(node.attrib.get("y", "nan"))
            if isclose(x, 76, abs_tol=0.1):
                if re.fullmatch(r"\d+", text_value):
                    minute_ticks[y - 8] = _as_int(text_value)
            elif isclose(x, 843, abs_tol=0.1) and re.fullmatch(r"\d+(?:,5)?", text_value):
                gb_ticks[y - 8] = _gb_quarters(text_value)
        if sorted(minute_ticks.values()) != list(range(0, 401, 50)) or sorted(
            gb_ticks.values()
        ) != list(range(0, 17, 2)):
            raise ValueError("Graph axis ticks do not show the researched units and scales")
        top = min(minute_ticks)
        bottom = max(minute_ticks)
        month_x: dict[str, float] = {}
        short_to_month = {f"{month[:3]}.": month for month in MONTHS}
        for node in root.findall(".//s:text", ns):
            label = (node.text or "").strip()
            if label in short_to_month:
                month_x[short_to_month[label]] = float(node.attrib["x"])
        if tuple(month_x) != MONTHS:
            raise ValueError("Graph does not label all twelve months in calendar order")

        minutes_by_month: dict[str, int] = {}
        gb_by_month: dict[str, int] = {}
        min_coords: dict[str, tuple[float, float]] = {}
        gb_coords: dict[str, tuple[float, float]] = {}
        for circle in root.findall(".//s:circle", ns):
            label = circle.attrib.get("aria-label", "")
            match = re.fullmatch(r"(\w+): ([\d.]+) (минут|ГБ)", label)
            if not match:
                raise ValueError("Chart point labels are not readable")
            month, value_text, unit = match.groups()
            if month not in MONTHS:
                raise ValueError("Chart point names an unknown month")
            value = match.group(2)
            x, y = float(circle.attrib["cx"]), float(circle.attrib["cy"])
            if not isclose(x, month_x[month], abs_tol=0.03):
                raise ValueError("Graph point is not aligned with its visible month label")
            if unit == "минут":
                minutes_by_month[month] = _as_int(value)
                min_coords[month] = (x, y)
                scale_value = (bottom - y) * 400 / (bottom - top)
                if not isclose(scale_value, _as_int(value), abs_tol=1.1):
                    raise ValueError("Minute point does not match the visible left axis")
                if circle.attrib.get("fill") != "#2463eb":
                    raise ValueError("Minute data points must use the solid blue series")
            else:
                quarters = float(value) * 4
                if not quarters.is_integer():
                    raise ValueError("Chart GB value is not on a quarter-GB tick")
                gb_by_month[month] = _as_int(quarters)
                gb_coords[month] = (x, y)
                scale_value = (bottom - y) * 4 / (bottom - top)
                if not isclose(scale_value, float(value), abs_tol=0.03):
                    raise ValueError("Internet point does not match the visible right axis")
                if circle.attrib.get("fill") != "#d04a35":
                    raise ValueError("Internet data points must use the red series")
        if tuple(minutes_by_month) != MONTHS or tuple(gb_by_month) != MONTHS:
            raise ValueError("Graph must have one point per month for each series")
        minutes = [minutes_by_month[month] for month in MONTHS]
        gb_quarters = [gb_by_month[month] for month in MONTHS]
        if tuple(minutes) != tuple(_as_int(v) for v in expected_minutes):
            raise ValueError("Visible minute labels differ from tariff world")
        if tuple(gb_quarters) != tuple(_as_int(v) for v in expected_gb):
            raise ValueError("Visible internet labels differ from tariff world")
        lines = root.findall(".//s:polyline", ns)
        if (
            len(lines) != 2
            or lines[0].attrib.get("stroke") != "#2463eb"
            or lines[0].attrib.get("stroke-dasharray")
            or lines[1].attrib.get("stroke") != "#d04a35"
            or not lines[1].attrib.get("stroke-dasharray")
        ):
            raise ValueError("Chart line styles do not distinguish minutes and internet")
        for line, coordinates, series in (
            (lines[0], min_coords, MONTHS),
            (lines[1], gb_coords, MONTHS),
        ):
            actual = [
                tuple(float(n) for n in pair.split(",")) for pair in line.attrib["points"].split()
            ]
            expected = [coordinates[month] for month in series]
            if len(actual) != 12 or any(
                not isclose(a, e, abs_tol=0.03)
                for point, exp in zip(actual, expected, strict=True)
                for a, e in zip(point, exp, strict=True)
            ):
                raise ValueError("Graph lines do not connect their displayed monthly points")
        visible_min = re.search(r"Минуты по месяцам: ([\d, ]+)\.", rendered.shared_context)
        visible_gb = re.search(
            r"Мобильный интернет по месяцам: ([\d., ]+) ГБ\.", rendered.shared_context
        )
        if visible_min is None or [_as_int(x) for x in visible_min.group(1).split(", ")] != minutes:
            raise ValueError("Visible minute context table differs from the chart")
        if (
            visible_gb is None
            or [_gb_quarters(x) for x in visible_gb.group(1).split(", ")] != gb_quarters
        ):
            raise ValueError("Visible internet context table differs from the chart")
        return minutes, gb_quarters

    @staticmethod
    def _visible_tariff(rendered: RenderedScenario) -> dict[str, int]:
        fixed = re.search(
            r"Тариф «Стандартный»: абонентская плата ([\d,]+) руб\./мес\.; включено (\d+) минут, ([\d.]+) ГБ и (\d+) SMS в месяц\.",  # noqa: E501
            rendered.shared_context,
        )
        extra = re.search(
            r"Сверх пакета: ([\d.]+) руб\./мин\.; интернет — ([\d,]+) руб\. за ([\d.]+) ГБ\. За год отправлено (\d+) SMS\.",  # noqa: E501
            rendered.shared_context,
        )
        if fixed is None or extra is None:
            raise ValueError("Visible shared context is missing the complete mobile tariff")
        monthly_fee, included_minutes, included_gb, included_sms = fixed.groups()
        extra_minute, pack_price, pack_gb, annual_sms = extra.groups()
        return {
            "monthly_fee_cents": _rubles_fraction(monthly_fee),
            "included_minutes": _as_int(included_minutes),
            "included_gb_quarters": _gb_quarters(included_gb),
            "included_sms_month": _as_int(included_sms),
            "annual_sms": _as_int(annual_sms),
            "extra_minute_cents": _rubles_fraction(extra_minute),
            "data_pack_quarters": _gb_quarters(pack_gb),
            "data_pack_price_cents": _rubles_fraction(pack_price),
        }

    def _visible_isp(
        self, scenario: ScenarioDraft, rendered: RenderedScenario
    ) -> dict[str, object]:
        table_bytes = self.renderer.asset_bytes(scenario, "home-internet-table")
        digest = sha256(table_bytes).hexdigest()
        if not any(asset.sha256 == digest for asset in rendered.assets):
            raise ValueError("Visible home internet table is not referenced by this scenario")
        root = ElementTree.fromstring(table_bytes)
        values = [
            (node.text or "").strip()
            for node in root.findall(".//{http://www.w3.org/2000/svg}text")
        ]
        expected_header = ["План", "Абонплата", "Включено", "Сверх пакета"]
        if values[:4] != expected_header or (len(values) - 4) % 4:
            raise ValueError("Visible home internet table has an invalid structure")
        plans: list[dict[str, object]] = []
        for offset in range(4, len(values), 4):
            name, fee, included, extra = values[offset : offset + 4]
            fee_match = re.fullmatch(r"([\d,]+) руб\./мес\.", fee)
            included_match = re.fullmatch(r"(\d+) МБ", included)
            extra_match = re.fullmatch(r"([\d,]+) руб\./МБ", extra)
            if fee not in {"нет"} and fee_match is None:
                raise ValueError("Visible ISP monthly fee is malformed")
            if included not in {"нет"} and included_match is None:
                raise ValueError("Visible ISP included limit is malformed")
            if extra not in {"нет"} and extra_match is None:
                raise ValueError("Visible ISP overage price is malformed")
            plans.append(
                {
                    "name": name,
                    "monthly_fee_cents": 0
                    if fee_match is None
                    else _rubles_fraction(fee_match.group(1)),
                    "included_mb": 0
                    if included_match is None
                    else _as_int(included_match.group(1)),
                    "per_mb_cents": 0
                    if extra_match is None
                    else _rubles_fraction(extra_match.group(1)),
                }
            )
        if len(plans) != 3:
            raise ValueError("Visible ISP table must list exactly three plans")
        return {"plans": plans}

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        minutes, gb = self._visible_series(scenario, rendered)
        visible_tariff = self._visible_tariff(rendered)
        visible_context: Mapping[str, object] = {
            "minutes": minutes,
            "gb_quarters": gb,
            "tariff": visible_tariff,
        }
        expected_family = {
            1: MINUTES_FAMILY,
            2: BILL_FAMILY,
            3: MINIMUM_FAMILY,
            4: PERCENT_FAMILY,
            5: ISP_FAMILY,
        }.get(question.position)
        if question.family_id != expected_family or question.scenario_seed != scenario.seed:
            raise ValueError("Question family or seed differs from the compatible source set")
        if len(question.hints) != 2 or not question.solution_steps:
            raise ValueError("Each tariff question requires two hints and a worked solution")
        if question.position == 1:
            found = re.findall(r"(\d+) мин", question.condition)
            if len(found) != 4:
                raise ValueError("Visible month-matching prompt must show four minute values")
            targets = [_as_int(v) for v in found]
            indexes = [minutes.index(value) for value in targets] if len(set(targets)) == 4 else []
            if len(indexes) != 4:
                raise ValueError("Visible target values do not have a unique month mapping")
            answer = "".join(str(i + 1) for i in indexes)
            if answer != question.canonical_answer:
                raise ValueError("Month-code answer does not follow visible target order")
        elif question.position == 2:
            names = {name: i for i, name in enumerate(MONTHS)}
            month = next((name for name in MONTHS if name in question.condition), None)
            if month is None:
                raise ValueError("Visible bill prompt does not name its month")
            index = names[month]
            answer = _rubles(_monthly_bill_cents(visible_context, index))
            if (
                not re.search(r"руб", rendered.shared_context)
                or answer != question.canonical_answer
            ):
                raise ValueError("Monthly bill does not match visible tariff and graph")
            if len(question.solution_steps) < 4 or _parse_rubles(
                question.solution_steps[-1].split(": ")[-1].split(" руб")[0]
            ) != _monthly_bill_cents(visible_context, index):
                raise ValueError("Monthly bill solution total is inconsistent")
        elif question.position == 3:
            answer = str(min(minutes))
        elif question.position == 4:
            increase = re.fullmatch(
                r"Абонентская плата выросла с ([\d,]+) руб\. до ([\d,]+) руб\. На сколько процентов она увеличилась\?",  # noqa: E501
                question.condition,
            )
            if increase is not None:
                old_fee, new_fee = (_parse_rubles(value) for value in increase.groups())
                numerator = (new_fee - old_fee) * 100
                if old_fee <= 0 or new_fee < old_fee or numerator % old_fee:
                    raise ValueError("Visible fee increase does not yield an exact percentage")
                answer = str(numerator // old_fee)
            else:
                raise ValueError("Visible fee prompt does not match compatible source task 461834")
            if answer != question.canonical_answer:
                raise ValueError("Fee percentage is incorrect")
        else:
            match = re.search(r"составляет (\d+) МБ", question.condition)
            if match is None:
                raise ValueError("Visible ISP prompt does not include data usage")
            usage = _as_int(match.group(1))
            visible_isp = self._visible_isp(scenario, rendered)
            visible_isp["usage_mb"] = usage
            costs = _isp_costs_cents(visible_isp, usage)
            if costs.count(min(costs)) != 1:
                raise ValueError("Visible ISP costs do not have a unique minimum")
            answer = _rubles(min(costs))
            if answer != question.canonical_answer:
                raise ValueError("Cheapest ISP answer is incorrect")
        if answer != question.canonical_answer:
            raise ValueError("Oracle answer mismatch")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(question.position for question in questions) != (1, 2, 3, 4, 5):
            raise ValueError("TARIFF bundle must contain all five ordered questions")
        if any(question.scenario_seed != scenario.seed for question in questions):
            raise ValueError("TARIFF questions must share one scenario seed")
        expected_families = (
            MINUTES_FAMILY,
            BILL_FAMILY,
            MINIMUM_FAMILY,
            PERCENT_FAMILY,
            ISP_FAMILY,
        )
        if tuple(question.family_id for question in questions) != expected_families:
            raise ValueError("TARIFF bundle differs from its researched compatible set")
        graph = next(
            (
                a
                for a in rendered.assets
                if a.content_type == "image/svg+xml"
                and a.sha256
                == sha256(self.renderer.asset_bytes(scenario, "usage-chart")).hexdigest()
            ),
            None,
        )
        table = next(
            (
                a
                for a in rendered.assets
                if a.content_type == "image/svg+xml"
                and a.sha256
                == sha256(self.renderer.asset_bytes(scenario, "home-internet-table")).hexdigest()
            ),
            None,
        )
        if graph is None or table is None:
            raise ValueError("Shared graph and ISP table must be rendered exactly once")
        if len(rendered.assets) != 2 or len({asset.sha256 for asset in rendered.assets}) != 2:
            raise ValueError("TARIFF must contain one graph and one table asset")


class _Adapter:
    story_code: str
    generator: ScenarioGenerator
    question_builder: QuestionBuilder
    independent_oracle: IndependentOracle
    renderer: Renderer
    answer_policies: Mapping[tuple[str, str], AnswerPolicy]
    family_registry: tuple[FamilyRegistration, ...]

    def __init__(
        self,
        generator: TariffGenerator,
        question_builder: TariffQuestionBuilder,
        oracle: TariffOracle,
        renderer: TariffRenderer,
        answer_policies: Mapping[tuple[str, str], TariffAnswerPolicy],
        family_registry: tuple[FamilyRegistration, ...],
    ) -> None:
        self.story_code = "TARIFF"
        self.generator = generator
        self.question_builder = question_builder
        self.independent_oracle = oracle
        self.renderer = renderer
        self.answer_policies = answer_policies
        self.family_registry = family_registry


def build_adapter(*, enabled_families: frozenset[str] = frozenset()) -> StoryAdapter:
    unknown = enabled_families - frozenset(IMPLEMENTED_FAMILIES)
    if unknown:
        raise ValueError(f"Cannot enable unsupported TARIFF families: {sorted(unknown)}")
    generator = TariffGenerator()
    question_builder = TariffQuestionBuilder()
    renderer = TariffRenderer()
    oracle = TariffOracle(renderer)
    policies = {
        (f"tariff.{family.lower()}", "1"): TariffAnswerPolicy(f"tariff.{family.lower()}")
        for family in IMPLEMENTED_FAMILIES
    }
    registrations = (
        *(
            FamilyRegistration(
                family_id, position, status, f"tariff.{family_id.lower()}", "1", False, source_ids
            )
            for family_id, position, status, source_ids in DISABLED_FAMILIES
        ),
        *(
            FamilyRegistration(
                family_id,
                position,
                FamilyStatus.ENABLED_CANDIDATE,
                f"tariff.{family_id.lower()}",
                "1",
                family_id in enabled_families,
                SET_A_SOURCES[family_id],
            )
            for position, family_id in (
                (1, MINUTES_FAMILY),
                (2, BILL_FAMILY),
                (3, MINIMUM_FAMILY),
                (4, PERCENT_FAMILY),
                (5, ISP_FAMILY),
            )
        ),
    )

    return _Adapter(generator, question_builder, oracle, renderer, policies, registrations)
