"""Display names for stable registry keys."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from app.math.first_rotation import topics
from app.persistence.part2_bank import ATLAS
from app.persistence.training_insights import family_name

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

_STUDENT_OVERRIDES = {
    "OGE09-L4A": "Линейное уравнение со скобками и переменной вне скобок",
    "OGE09-L4B": "Линейное уравнение со скобками в обеих частях",
    "OGE11-F01": "Сопоставление формул и графиков разных функций",
    "OGE11-F02": "Сопоставление графиков и формул разных функций",
    "OGE14-A01": "Член арифметической прогрессии в задаче про амфитеатр",
    "OGE14-A02": "Последний ряд как член арифметической прогрессии",
    "OGE14-A10": "Разность и заданный член арифметической прогрессии",
    "OGE17-E03": "Диагональ прямоугольника по её половине",
    "OGE17-P07": "Диагональ параллелограмма по её половине",
    "OGE19-AREAS-METRICS": "Выбор верных утверждений о площадях и длинах",
    "OGE19-CIRCLES": "Выбор верных утверждений об окружностях",
    "OGE19-LINES-ANGLES": "Выбор верных утверждений о прямых и углах",
    "OGE19-MIXED": "Выбор верных утверждений по разным темам геометрии",
    "OGE19-QUADRILATERALS": "Выбор верных утверждений о четырёхугольниках",
    "OGE19-TRIANGLES": "Выбор верных утверждений о треугольниках",
}


@lru_cache(maxsize=1)
def written() -> dict[str, dict[str, object]]:
    data = json.loads((ATLAS / "taxonomy.json").read_text(encoding="utf-8"))
    return {s["subtype_id"]: s for s in data["subtypes"]}


@lru_cache(maxsize=512)
def title(skill: str) -> str:
    if skill in _STUDENT_OVERRIDES:
        return _STUDENT_OVERRIDES[skill]
    if skill in _STORIES:
        return _STORIES[skill]
    if skill in written():
        return str(written()[skill]["title"])
    name = family_name(skill)
    return topics().get(skill, name) if name == "Тип из прежней версии" else name


@dataclass(frozen=True)
class TitleIssue:
    family: str
    title: str
    reason: str


_INTERNAL_LABEL = re.compile(
    r"(?:^|\s)(?:OGE\d+|[FCLRQSN]\d{1,3}|прототип\s*\d+)(?:\s|$)", re.I
)


def audit_student_titles(catalog: dict[str, int]) -> tuple[TitleIssue, ...]:
    """Audit public families without inventing broader pedagogical claims."""
    issues = []
    for family in sorted(catalog):
        label = title(family).strip()
        if not label or label == "Тип из прежней версии":
            issues.append(TitleIssue(family, label, "missing_student_title"))
        elif label == family or _INTERNAL_LABEL.search(label):
            issues.append(TitleIssue(family, label, "internal_id_visible"))
    return tuple(issues)
