"""Stable keys belong to registries; these links only recommend prerequisite practice."""

import json
from functools import lru_cache

from app.math.first_rotation import topics
from app.persistence.part2_bank import ATLAS
from app.persistence.training_insights import family_name

PREREQUISITES = {"OGE23-right-median": "OGE15-F14", "OGE23-trapezoid-area": "OGE15-F14"}

_STORIES = {
    "TYRES-TABLE-EXTREME": "Чтение таблицы размеров шин",
    "TYRES-SIDEWALL": "Высота боковины шины",
    "TYRES-DIAMETER": "Диаметр колеса",
    "TYRES-RADIUS-DELTA": "Изменение радиуса колеса",
    "TYRES-PERCENT-ROTATION": "Процентное изменение пути колеса",
    "PAPER-F01": "Размеры листов по таблице",
    "PAPER-F02": "Деление бумажного листа",
    "PAPER-F03": "Размер листа и округление",
    "PAPER-F04": "Отношение сторон листа",
    "PAPER-F06": "Отношение диагонали к стороне",
    "PAPER-F07": "Масштабирование шрифта",
    "TARIFF-F01-MONTHS-MINUTES": "Месяцы и расход минут",
    "TARIFF-F04-MONTHLY-BILL": "Плата за месяц",
    "TARIFF-F05-EXTREMUM": "Экстремум по диаграмме",
    "TARIFF-F09-PERCENT-FEE": "Изменение абонентской платы",
    "TARIFF-F12-HOME-ISP": "Сравнение тарифов интернета",
    "FLAT-01-ROOM-MATCH": "Помещения на плане",
    "FLAT-02-PARQUET-PACK": "Упаковки паркета",
    "FLAT-02-TILE-PACK": "Упаковки плитки",
    "FLAT-03-RECT-AREA": "Площадь помещения",
    "FLAT-04-RECT-PERCENT": "Сравнение площадей в процентах",
    "FLAT-05-INTERNET-MIN": "Выгодный тариф",
    "FLAT-05-WASHER-MIN": "Полная стоимость покупки",
    "GARDEN-01-IDENTIFY": "Объекты на плане участка",
    "GARDEN-02-TILES-PACKS": "Плитка для участка",
    "GARDEN-04-PERIMETER-POLYGON": "Периметр по плану",
    "GARDEN-07-PERCENT-BUILDINGS": "Доля площади застройки",
    "GARDEN-09-HEAT-BREAKEVEN": "Окупаемость отопления",
    "STOVE-F01-CAPACITY-LIMITS": "Характеристики печей по таблице",
    "STOVE-F02-ATTRIBUTE-MATCH": "Сопоставление характеристик печей",
    "STOVE-F03-VOLUME": "Объём помещения",
    "STOVE-F04-FLOOR-AREA": "Площадь пола",
    "STOVE-F05-WALL-AREA-NET": "Площадь стен с проёмами",
    "STOVE-F06-PURCHASE-EXTRA-COSTS": "Дополнительные расходы на печь",
    "STOVE-F07-FIT-WOOD-DELIVERY": "Выбор печи с доставкой",
    "STOVE-F08-COST-COMPARISON": "Сравнение стоимости печей",
    "STOVE-F09-DIRECT-DISCOUNT": "Цена после скидки",
    "STOVE-F10-REVERSE-DISCOUNT": "Цена до скидки",
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": "Последовательные скидки",
    "STOVE-F12-ARCH-RADIUS": "Радиус арки",
}


@lru_cache(maxsize=1)
def written() -> dict[str, dict[str, object]]:
    data = json.loads((ATLAS / "taxonomy.json").read_text())
    return {s["subtype_id"]: s for s in data["subtypes"]}


@lru_cache(maxsize=512)
def title(skill: str) -> str:
    if skill in _STORIES:
        return _STORIES[skill]
    if skill in written():
        return str(written()[skill]["title"])
    name = family_name(skill)
    return topics().get(skill, name) if name == "Тип из прежней версии" else name
