"""Reproduce the all-enabled-family OGE 1–14 audit sample and mobile previews.

This intentionally reuses the runtime registry, each generator's independent
oracle, and each production candidate scheduler. It does not change generator
state or claim that generated analogues are official source tasks.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import random
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image

from app.bot.scenario_training import PUBLIC_FAMILIES, public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "OGE_BANK_QUALITY_AUDIT.json"
MARKDOWN_REPORT = ROOT / "reports" / "OGE_BANK_QUALITY_AUDIT.md"
ASSET_DIR = ROOT / "reports" / "assets" / "oge-bank-audit"
SAMPLE_SEEDS = 50
SCENARIO_SEEDS = 600
EXTENDED_SEEDS = {"OGE07-C03": 300, "OGE07-C04": 300}
EXTENDED_SCENARIO_FAMILIES = {
    "FLAT-03-RECT-AREA",
    "FLAT-04-RECT-PERCENT",
    "FLAT-05-WASHER-MIN",
    "GARDEN-04-PERIMETER-POLYGON",
    "GARDEN-07-PERCENT-BUILDINGS",
    "PAPER-F03",
    "PAPER-F04",
    "PAPER-F06",
}
SEED_NAMESPACE = 20271112
MOBILE_WIDTH = 390

QUALITY_REPORTS: dict[int | str, str] = {
    "1-5": "reports/OGE15_V2_AUDIT.md",
    "1-5-source-review": "reports/OGE15_V2_FAMILY_REVIEW.md",
    "1-5-source-acceptance": "reports/OGE15_V2_SOURCE_ACCEPTANCE.md",
    "1-5-diversity": "reports/OGE15_V2_DIVERSITY.md",
    6: "reports/oge6-0.2.1-quality.json",
    7: "reports/oge07-quality.json",
    8: "reports/oge8-quality.json",
    9: "reports/oge9-quality.json",
    10: "reports/oge10-quality.json",
    11: "reports/oge11-quality.json",
    12: "reports/oge12-quality.json",
    13: "reports/oge13-quality.json",
    14: "reports/oge14-quality.json",
}

COMPLEXITY: dict[int, dict[str, int]] = {
    6: {
        "OGE06-F001-ADD": 2,
        "OGE06-F001-SUB": 2,
        "OGE06-F002-MUL": 2,
        "OGE06-F002-DIV": 3,
        "OGE06-F004-DEC-ADD": 2,
        "OGE06-F004-DEC-SUB": 2,
        "OGE06-F004-DEC-MUL": 2,
        "OGE06-F006-MIXED-MINUS-DECIMAL": 3,
        "OGE06-F008-REDUCED-NUMERATOR": 3,
        "OGE06-F009-PRESCRIBED-NUMERATOR": 3,
    },
    7: {
        "OGE07-C01": 2,
        "OGE07-C02": 2,
        "OGE07-C03": 2,
        "OGE07-C04": 1,
        "OGE07-C06": 2,
        "OGE07-N01": 3,
        "OGE07-N04": 3,
    },
    8: {"OGE08-R04": 2, "OGE08-R08": 3},
    9: {
        "OGE09-L1": 2,
        "OGE09-L2": 2,
        "OGE09-L3": 3,
        "OGE09-L4A": 3,
        "OGE09-L4B": 3,
        "OGE09-K2": 3,
        "OGE09-K3": 3,
        "OGE09-K6": 4,
    },
    10: {
        "OGE10-F001-DRAW-CATEGORY": 2,
        "OGE10-F002-COMPLEMENT": 2,
        "OGE10-F006-EMPIRICAL-FREQUENCY": 2,
        "OGE10-F007-DISJOINT-UNION-RESIDUAL": 3,
        "OGE10-F008-REMAINDER-CATEGORY": 2,
        "OGE10-F009-OVERLAPPING-GROUPS": 3,
    },
    11: {f"OGE11-F{i:02d}": score for i, score in enumerate((3, 3, 2, 2, 3, 3, 2, 3), 1)},
    12: {
        "OGE12-R001": 3,
        "OGE12-R002": 2,
        "OGE12-R003": 2,
        "OGE12-R004": 2,
        "OGE12-R005": 4,
        "OGE12-R010": 3,
        "OGE12-R011": 2,
        "OGE12-R012": 3,
    },
    13: {
        "OGE13-L01": 2,
        "OGE13-L02": 2,
        "OGE13-Q01": 3,
        "OGE13-Q02": 3,
        "OGE13-Q03": 3,
        "OGE13-Q04": 3,
        "OGE13-S01": 3,
        "OGE13-S02": 3,
        "OGE13-S03": 3,
    },
    14: {
        "OGE14-A01": 2,
        "OGE14-A02": 2,
        "OGE14-A03": 3,
        "OGE14-A05": 3,
        "OGE14-A07": 3,
        "OGE14-A08": 3,
        "OGE14-A09": 2,
        "OGE14-A10": 3,
        "OGE14-G01": 3,
        "OGE14-G02": 3,
        "OGE14-G03": 3,
        "OGE14-G04": 3,
    },
}
SCENARIO_COMPLEXITY = {
    "TYRES-TABLE-EXTREME": 2,
    "TYRES-SIDEWALL": 2,
    "TYRES-DIAMETER": 3,
    "TYRES-RADIUS-DELTA": 3,
    "TYRES-PERCENT-ROTATION": 3,
    "PAPER-F01": 2,
    "PAPER-F02": 2,
    "PAPER-F03": 2,
    "PAPER-F04": 3,
    "PAPER-F06": 3,
    "PAPER-F07": 3,
    "STOVE-F01-CAPACITY-LIMITS": 2,
    "STOVE-F02-ATTRIBUTE-MATCH": 2,
    "STOVE-F03-VOLUME": 2,
    "STOVE-F04-FLOOR-AREA": 2,
    "STOVE-F05-WALL-AREA-NET": 3,
    "STOVE-F06-PURCHASE-EXTRA-COSTS": 2,
    "STOVE-F07-FIT-WOOD-DELIVERY": 3,
    "STOVE-F08-COST-COMPARISON": 2,
    "STOVE-F09-DIRECT-DISCOUNT": 2,
    "STOVE-F10-REVERSE-DISCOUNT": 2,
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": 3,
    "STOVE-F12-ARCH-RADIUS": 3,
    "TARIFF-F01-MONTHS-MINUTES": 3,
    "TARIFF-F04-MONTHLY-BILL": 2,
    "TARIFF-F05-EXTREMUM": 3,
    "TARIFF-F09-PERCENT-FEE": 2,
    "TARIFF-F12-HOME-ISP": 3,
    "GARDEN-01-IDENTIFY": 2,
    "GARDEN-02-TILES-PACKS": 2,
    "GARDEN-04-PERIMETER-POLYGON": 3,
    "GARDEN-07-PERCENT-BUILDINGS": 2,
    "GARDEN-09-HEAT-BREAKEVEN": 3,
    "FLAT-01-ROOM-MATCH": 2,
    "FLAT-02-TILE-PACK": 2,
    "FLAT-02-PARQUET-PACK": 2,
    "FLAT-03-RECT-AREA": 2,
    "FLAT-04-RECT-PERCENT": 3,
    "FLAT-05-WASHER-MIN": 2,
    "FLAT-05-INTERNET-MIN": 3,
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _numeric_tokens(text: str) -> list[str]:
    return re.findall(r"(?<!\w)[−-]?\d+(?:[,.]\d+)?(?:/\d+)?", text)


def _parameter_numbers(value: Any, path: str = "parameters") -> list[tuple[str, float]]:
    if isinstance(value, dict):
        return [
            pair
            for key, item in value.items()
            for pair in _parameter_numbers(item, f"{path}.{key}")
        ]
    if isinstance(value, list | tuple):
        return [pair for item in value for pair in _parameter_numbers(item, f"{path}[]")]
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [(path, float(value))]
    if isinstance(value, str) and re.fullmatch(r"[−-]?\d+(?:[,.]\d+)?(?:/\d+)?", value):
        normalized = value.replace("−", "-").replace(",", ".")
        return [(path, float(Fraction(normalized)))]
    return []


def _seed_sequence(number: int, family: str, count: int) -> list[int]:
    token = int.from_bytes(
        hashlib.sha256(f"{SEED_NAMESPACE}:{number}:{family}".encode()).digest()[:8],
        "big",
    )
    rng = random.Random(token)
    seeds = [rng.randrange(2**63) for _ in range(count)]
    if family == "OGE07-C04" and count:
        seeds[0] = 6
    return seeds


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_shape(item) for item in value]
    if isinstance(value, int | float) or (
        isinstance(value, str) and re.fullmatch(r"[−-]?\d+(?:[,.]\d+)?(?:/\d+)?", value)
    ):
        return "#"
    return value


def _condition(item: Any, number: int) -> str:
    return str(getattr(item, "condition", getattr(item, "equation_text", "")))


def _answer(item: Any, number: int) -> str:
    if number == 7 and hasattr(item, "correct_option_index"):
        index = int(item.correct_option_index) - 1
        options = tuple(item.options)
        return (
            str(options[index])
            if 0 <= index < len(options)
            else f"<invalid-index:{item.correct_option_index}>"
        )
    return str(getattr(item, "correct_answer", getattr(item, "canonical_answer", "")))


def _options(item: Any) -> list[str]:
    if hasattr(item, "option_texts"):
        return [str(value) for value in item.option_texts]
    if hasattr(item, "options"):
        return [str(value) for value in item.options]
    return []


def _sample_record(item: Any, number: int, seed: int, valid: bool) -> dict[str, Any]:
    condition = _condition(item, number)
    snapshot = item.to_snapshot() if hasattr(item, "to_snapshot") else {}
    model = getattr(item, "math_model", None)
    if model is None:
        model = getattr(item, "parameters", getattr(item, "variables", None))
    if model is None and hasattr(item, "graphs"):
        model = [{"kind": g.kind, "coefficients": g.coefficients} for g in item.graphs]
    if model is None and hasattr(item, "graph_model"):
        model = item.graph_model
    options = _options(item)
    if not options:
        options = [str(value) for value in snapshot.get("option_texts", [])]
    answer = _answer(item, number)
    correct_option_positions = [
        index + 1 for index, option in enumerate(options) if option == answer
    ]
    return {
        "seed": seed,
        "valid_oracle": bool(valid),
        "condition": condition,
        "answer": answer,
        "options": options,
        "correct_option_position": (
            correct_option_positions[0] if len(correct_option_positions) == 1 else None
        ),
        "hints": _jsonable(getattr(item, "hints", snapshot.get("hints", []))),
        "solution": _jsonable(
            getattr(
                item,
                "solution",
                getattr(item, "solution_steps", snapshot.get("solution_steps", [])),
            )
        ),
        "construction_signature": _jsonable(_shape(_jsonable(model))),
        "construction_parameters": _jsonable(model),
        "fingerprint": str(getattr(item, "fingerprint", snapshot.get("fingerprint", ""))),
        "image_sha256": str(getattr(item, "image_sha256", getattr(item, "png_sha256", ""))),
        "source_ids": _jsonable(getattr(item, "reference_ids", snapshot.get("reference_ids", []))),
        "content_provenance": _jsonable(
            snapshot.get("content_provenance", snapshot.get("provenance", []))
        ),
    }


def _stable(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _oracle(number: int, family: str, item: Any) -> bool:
    if number == 6:
        from app.math.oracle import validate_rendered_problem

        validate_rendered_problem(item)
        return True
    if number == 7:
        if hasattr(item, "graph_model"):
            from app.math.oge07_graph import audit_graph_explanation, audit_graph_problem, audit_png
            from app.math.oge07_validation import validate_task7_snapshot

            return (
                audit_graph_problem(item)
                and audit_graph_explanation(item)
                and audit_png(item.graph_model, item.png)
                and validate_task7_snapshot(item.to_snapshot())
            )
        from app.math.numbers import audit_condition, audit_explanation
        from app.math.oge07_validation import validate_task7_snapshot

        return (
            audit_condition(family, item.condition, item.options, item.correct_option_index)
            and audit_explanation(item)
            and validate_task7_snapshot(item.to_snapshot())
        )
    if number == 8:
        from app.math.oge8 import verify_problem

        return verify_problem(item)
    if number == 9:
        from app.math.equations import validate_rendered_problem

        validate_rendered_problem(item)
        return True
    if number == 10:
        from app.math.probability import validate_rendered_problem

        return validate_rendered_problem(item)
    if number == 11:
        from app.math.oge11 import verify

        return verify(item)[0]
    if number == 12:
        from app.math.formulas import validate_rendered_problem

        return validate_rendered_problem(item)
    if number == 13:
        from app.math.inequalities import validate, validate_snapshot

        return validate(item) and validate_snapshot(item.to_snapshot())
    if number == 14:
        from app.math.progressions import audit_condition, solve_condition

        return (
            audit_condition(family, item.condition, item.parameters)
            and solve_condition(family, item.condition) == item.exact_value
        )
    raise ValueError(f"Unsupported task number {number}")


def _ordinary_generator(number: int) -> tuple[tuple[str, ...], Callable[[str, int], Any]]:
    module_names = {
        6: ("app.math.registry", "app.math.generator", "GENERATOR_SPECS", "generate"),
        7: ("app.math.oge07_scheduler", "app.math.numbers", "ALL_FAMILIES", "generate"),
        8: ("app.math.oge8", "app.math.oge8", "ALL_FAMILIES", "generate"),
        9: ("app.math.equations", "app.math.equations", "ENABLED_FAMILIES", "generate_equation"),
        10: ("app.math.probability", "app.math.probability", "ENABLED_FAMILIES", "generate"),
        11: ("app.math.oge11", "app.math.oge11", "FAMILIES", "generate"),
        12: ("app.math.formulas", "app.math.formulas", "ALL_FAMILIES", "generate"),
        13: ("app.math.inequalities", "app.math.inequalities", "ALL_FAMILIES", "generate"),
        14: ("app.math.progressions", "app.math.progressions", "ALL_FAMILIES", "generate"),
    }
    registry_name, generator_name, family_attr, function_name = module_names[number]
    registry = importlib.import_module(registry_name)
    generator = importlib.import_module(generator_name)
    if number == 6:
        families = tuple(spec.family_id for spec in getattr(registry, family_attr))
    else:
        enabled = set(generator.ENABLED_FAMILIES)
        all_ids = getattr(registry, family_attr)
        families = tuple(family for family in all_ids if family in enabled)
    if number == 7:
        from app.math.oge07_graph import GRAPH_SOURCES, generate_graph_problem

        families = tuple(registry.ENABLED_FAMILIES)
        return families, lambda family, seed: (
            generate_graph_problem(family, seed)
            if family in GRAPH_SOURCES
            else generator.generate(family, seed)
        )
    function = getattr(generator, function_name)
    return families, lambda family, seed: function(family, seed)


def _complexity(number: int, family: str, examples: list[dict[str, Any]]) -> dict[str, Any]:
    score = COMPLEXITY.get(number, {}).get(family, 3)
    example = examples[0] if examples else {}
    operation = family.replace(f"OGE{number:02d}-", "").replace("OGE15-", "")
    reasons = {
        6: (
            "Одна рациональная/десятичная операция; score 3 используется для деления или "
            "преобразования дроби, где нужно удерживать несколько шагов."
        ),
        7: (
            "Сравнение чисел/отрезков или чтение точки графика; C04 отдельно проверяется "
            "на то, что варианты требуют сравнения, а не выдают ответ форматом числа."
        ),
        8: "Упрощение радикалов и контроль раскрытия квадрата; требуется точное преобразование.",
        9: (
            "Решение линейного/квадратного уравнения с проверкой целевого корня; K6 "
            "оценён выше из-за нескольких коэффициентов и корней."
        ),
        10: (
            "Построение вероятностной доли по видимой выборке; объединение/пересечение "
            "групп требует отдельного счёта событий."
        ),
        11: (
            "Сопоставление графиков и формул; знаки требуют меньшего рассуждения, "
            "обратная зависимость и коэффициенты — проверки контрольных значений."
        ),
        12: (
            "Выразить величину из формулы и подставить данные с единицами; оценки "
            "учитывают число преобразований и возможное извлечение корня."
        ),
        13: (
            "Решить линейное/квадратное неравенство либо систему и сопоставить множество "
            "решений с интервалами; система требует пересечения условий."
        ),
        14: (
            "Найти член арифметической/геометрической прогрессии; геометрический рост "
            "и неизвестные начальные данные требуют дополнительных преобразований."
        ),
    }
    if number == 7 and family == "OGE07-C04":
        reason = (
            "Оценка 1 обусловлена воспроизводимыми seed, где правильный вариант — целая "
            "граница отрезка, а все отвлекающие числа очевидно вне него; пример и частота "
            "приведены в findings."
        )
    else:
        reason = reasons.get(
            number,
            "Оценка по видимой операции в пяти примерах; seed и условие приведены в JSON.",
        )
    if example.get("condition"):
        reason = (
            f"{reason} Конкретная опора оценки — seed {example.get('seed')}: "
            f"{example['condition']} Ответ {example.get('answer', '—')}."
        )
    return {
        "score": score,
        "rationale": reason,
        "family_code": operation,
        "reviewed_example_seed": example.get("seed"),
    }


def _summarize(
    number: int, family: str, records: list[dict[str, Any]], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    conditions = [" ".join(row["condition"].split()) for row in records]
    display_content = [
        json.dumps(
            [
                condition,
                row.get("options", []),
                row.get("image_sha256", row.get("asset_sha256", [])),
                row.get("construction_signature"),
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        for condition, row in zip(conditions, records, strict=True)
    ]
    answers = [row["answer"] for row in records]
    fps = [row["fingerprint"] for row in records if row["fingerprint"]]
    signatures = [
        json.dumps(row["construction_signature"], ensure_ascii=False, sort_keys=True)
        for row in records
    ]
    duplicate_count = len(display_content) - len(set(display_content))
    text_duplicate_count = len(conditions) - len(set(conditions))
    numeric = [token for condition in conditions for token in _numeric_tokens(condition)]
    parameter_values: dict[str, list[float]] = {}
    for row in records:
        for path, value in _parameter_numbers(row.get("construction_parameters")):
            parameter_values.setdefault(path, []).append(value)
    number_types = Counter(
        "fraction" if "/" in x else "decimal" if "," in x or "." in x else "integer"
        for x in numeric
    )
    record = {
        "sample_count": len(records),
        "seeds": [row["seed"] for row in records],
        "unique_conditions": len(set(display_content)),
        "unique_condition_texts": len(set(conditions)),
        "condition_repeat_count": duplicate_count,
        "condition_repeat_rate": round(duplicate_count / len(records), 4) if records else None,
        "identical_condition_text_count": text_duplicate_count,
        "unique_answers": len(set(answers)),
        "answer_distribution": dict(Counter(answers).most_common(15)),
        "unique_fingerprints": len(set(fps)),
        "unique_construction_signatures": len(set(signatures)),
        "visible_number_token_types": dict(number_types),
        "visible_number_min": min(
            (float(x.replace("−", "-").replace(",", ".")) for x in numeric if "/" not in x),
            default=None,
        ),
        "visible_number_max": max(
            (float(x.replace("−", "-").replace(",", ".")) for x in numeric if "/" not in x),
            default=None,
        ),
        "parameter_distributions": {
            path: {
                "sampled_values": len(values),
                "unique_values": len(set(values)),
                "minimum": min(values),
                "maximum": max(values),
                "most_common": Counter(values).most_common(10),
            }
            for path, values in parameter_values.items()
        },
        "oracle_failures": failures,
        "generation_failure_count": sum(
            item.get("failure_kind") == "generation_error" for item in failures
        ),
        "oracle_rejection_count": sum(
            item.get("failure_kind") == "oracle_false" for item in failures
        ),
        "representative_examples": records[:5],
        "samples": records,
        "method_complexity": _complexity(number, family, records[:5]),
        "max_condition_characters": max((len(row["condition"]) for row in records), default=0),
    }
    option_samples = [row["options"] for row in records if row["options"]]
    if option_samples:
        record["option_count_distribution"] = dict(Counter(map(len, option_samples)))
        record["option_unique_values_by_position"] = [
            len({options[index] for options in option_samples if len(options) > index})
            for index in range(max(map(len, option_samples)))
        ]
        record["duplicate_option_sets"] = sum(
            len(opts) != len(set(opts)) for opts in option_samples
        )
        record["correct_option_position_distribution"] = dict(
            Counter(
                row["correct_option_position"]
                for row in records
                if row.get("correct_option_position") is not None
            )
        )
    return record


def _family_audit(number: int, family: str, sample_size: int) -> tuple[dict[str, Any], list[Any]]:
    families, make = _ordinary_generator(number)
    if family not in families:
        raise ValueError(f"Family {family} is not runtime-enabled for task {number}")
    records: list[dict[str, Any]] = []
    preview_items: list[Any] = []
    failures: list[dict[str, Any]] = []
    for seed in _seed_sequence(number, family, sample_size):
        try:
            problem = make(family, seed)
            valid = _oracle(number, family, problem)
            record = _sample_record(problem, number, seed, valid)
            records.append(record)
            preview_items.append(problem)
            if not valid:
                failures.append(
                    {
                        "seed": seed,
                        "failure_kind": "oracle_false",
                        "reason": "independent oracle returned false",
                    }
                )
        except Exception as error:  # record the failing seed and continue the family audit
            failures.append(
                {
                    "seed": seed,
                    "failure_kind": "generation_error",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
    summary = _summarize(number, family, records, failures)
    if family == "OGE07-C04":
        boundary_examples = []
        integer_targets = 0
        boundary_answers = 0
        for row in records:
            interval = re.search(r"\[([^;]+); ([^]]+)\]", row["condition"])
            if interval is None:
                continue
            target = Fraction(row["answer"].replace("−", "-").replace(",", "."))
            endpoints = tuple(
                Fraction(value.replace("−", "-").replace(",", ".")) for value in interval.groups()
            )
            integer_targets += target.denominator == 1
            if target in endpoints:
                boundary_answers += 1
                if len(boundary_examples) < 10:
                    boundary_examples.append(row)
        summary["integer_target_count"] = integer_targets
        summary["integer_target_rate"] = round(integer_targets / len(records), 4)
        summary["integer_boundary_answer_count"] = boundary_answers
        summary["integer_boundary_answer_rate"] = round(boundary_answers / len(records), 4)
        summary["integer_boundary_examples"] = boundary_examples
        summary["source_comparison"] = {
            "source_id": "369728",
            "source_prototype": "68/19 принадлежит [3;4]",
            "generated_target_domain": (
                "denominators 2, 3, 4, 5, or 10; finite decimals in the displayed options"
            ),
        }
    return summary, preview_items


def _diversity_keys(row: dict[str, Any], scenario: bool) -> dict[str, str]:
    """Separate question-level math from shared-story and presentation changes."""
    question_text = " ".join(str(row.get("question_text", row.get("condition", ""))).split())
    params = row.get("construction_parameters")
    if isinstance(params, str):
        try:
            params = json.loads(params.replace("'", '"'))
        except (json.JSONDecodeError, TypeError):
            pass
    if params in (None, {}, []):
        numeric_parameters = _numeric_tokens(question_text)
        params = (
            {"visible_numeric_tokens": numeric_parameters}
            if numeric_parameters
            else {"question_condition": question_text}
        )
    # Story assets belong to the shared context and must not inflate the
    # mathematical diversity of one question. Ordinary graph images are part
    # of the question itself, so their digest is retained there.
    math_key = _stable(params)
    return {
        "full_story": str(row.get("full_story_fingerprint", "")) if scenario else "",
        "question_condition": _stable(
            [question_text, row.get("options", []) if not scenario else []]
        ),
        "significant_parameters": math_key,
        "cosmetic_presentation": _stable([question_text, row.get("answer", ""), math_key]),
    }


def _numeric_values(text: str) -> list[Fraction]:
    values: list[Fraction] = []
    for token in _numeric_tokens(text):
        try:
            values.append(Fraction(token.replace("−", "-").replace(",", ".")))
        except (ValueError, ZeroDivisionError):
            continue
    return values


_OPERATION_CONCEPTS = {
    "rounding": ("округл", "round"),
    "area": ("площад", "area"),
    "perimeter": ("периметр", "perimeter"),
    "ratio": ("отношени", "ratio", "во сколько раз"),
    "percent": ("процент", "percent", "%"),
    "probability": ("вероят", "probabilit", "случайн"),
    "equation": ("уравнен", "equation"),
    "inequality": ("неравен", "inequalit", "промежуток решен"),
    "graph": ("график", "graph", "парабол", "гипербол"),
    "progression": ("прогресси", "progression", "арифметическ", "геометрическ"),
    "unit_conversion": ("единиц", "миллиметр", "сантиметр", "километр", "перевед"),
    "extremum": ("миним", "максим", "наибольш", "наименьш", "extremum"),
    "counting": ("подсчит", "количеств", "сколько", "count"),
}


def _operation_concepts(text: str) -> set[str]:
    lowered = text.lower()
    return {
        concept
        for concept, terms in _OPERATION_CONCEPTS.items()
        if any(term in lowered for term in terms)
    }


def _historical_story_diversity() -> dict[str, dict[str, int]]:
    path = ROOT / "reports" / "OGE15_V2_DIVERSITY.md"
    if not path.exists():
        return {}
    parsed: dict[str, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or not cells[0].startswith(
            ("FLAT-", "GARDEN-", "PAPER-", "STOVE-", "TARIFF-", "TYRES-")
        ):
            continue
        try:
            parsed[cells[0]] = {
                "sample_count": int(cells[1]),
                "unique_conditions": int(cells[2]),
                "unique_signatures": int(cells[3]),
                "unique_answers": int(cells[4]),
                "most_common_answer_count": int(cells[5]),
                "explanations": int(cells[6]),
            }
        except ValueError:
            continue
    return parsed


def _diagnose_family(family_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Common deterministic signals; signals require content/source review before promotion."""
    samples = row.get("samples", [])
    scenario = row.get("exam_number") == "1-5"
    keys = [_diversity_keys(sample, scenario) for sample in samples]
    count = len(samples)
    answers = [str(sample.get("answer", "")) for sample in samples]
    answer_counts = Counter(answers)
    question_conditions = [key["question_condition"] for key in keys]
    math_parameters = [key["significant_parameters"] for key in keys]
    story_keys = [key["full_story"] for key in keys if key["full_story"]]
    cosmetic = [key["cosmetic_presentation"] for key in keys]
    signals: list[dict[str, Any]] = []
    review_items: list[str] = []

    def signal(code: str, detail: str, seeds: list[int] | None = None) -> None:
        all_seeds = seeds or []
        chosen_seeds = all_seeds[:5]
        signals.append(
            {
                "code": code,
                "detail": detail,
                "seeds": all_seeds,
                "signal_count": len(all_seeds) if seeds is not None else None,
                "signal_rate": (
                    round(len(all_seeds) / count, 4) if count and seeds is not None else None
                ),
                "examples": [sample for sample in samples if sample.get("seed") in chosen_seeds][
                    :5
                ],
            }
        )

    if count and len(set(answers)) <= max(1, round(count * 0.02)):
        signal(
            "answer_support_extremely_narrow",
            f"{len(set(answers))} unique answers / {count} samples",
            [int(sample["seed"]) for sample in samples],
        )
        review_items.append(
            "check whether fixed answer is natural source capacity or hidden answer"
        )
    unique_parameter_count = len(set(math_parameters))
    if count and unique_parameter_count <= max(1, round(count * 0.02)):
        signal(
            "question_parameter_support_extremely_narrow",
            f"{len(set(math_parameters))} significant parameter signatures / {count} samples",
            [int(sample["seed"]) for sample in samples],
        )
        review_items.append("check repeated mathematical operation and parameter set")
    repeat_rate = 1 - len(set(question_conditions)) / count if count else 0
    # Same wording is often the intended task template; only raise a repeat
    # signal when the math parameters also collapse to a narrow support.
    if repeat_rate >= 0.2 and unique_parameter_count <= max(2, round(count * 0.2)):
        signal(
            "question_condition_repeats",
            f"{repeat_rate:.1%} exact normalized question-condition repeats",
            [
                int(sample["seed"])
                for sample, condition in zip(samples, question_conditions, strict=True)
                if question_conditions.count(condition) > 1
            ],
        )
        review_items.append(
            "inspect repeats to separate natural finite capacity from cosmetic variation"
        )
    if (
        count >= 50
        and len(set(question_conditions)) == 1
        and unique_parameter_count == 1
        and len(set(answers)) == 1
    ):
        signal(
            "question_construction_collapsed_to_one_observed_case",
            "All sampled seeds produce one normalized question, one significant parameter "
            "set, and one answer",
            [int(sample["seed"]) for sample in samples],
        )
        review_items.append(
            "check whether a single observed construction is intentional finite capacity or "
            "insufficient content variation"
        )
    if scenario and story_keys and len(set(story_keys)) > len(set(question_conditions)):
        signal(
            "shared_story_variation_exceeds_question_variation",
            "Full-story fingerprints vary more often than question-specific conditions",
            [int(sample["seed"]) for sample in samples],
        )
        review_items.append("do not count shared-context changes as new question constructions")

    # Interval multiple-choice diagnostic: endpoint/correct-option patterns plus
    # distractor distance are only a review trigger, never a confirmed defect.
    interval_pattern = re.compile(r"[\[(]([^;]+);\s*([^\])]+)[\])]")
    suspicious: list[int] = []
    perfect_square_endpoint: list[int] = []
    for sample in samples:
        interval_match = interval_pattern.search(str(sample.get("condition", "")))
        if not interval_match:
            continue
        try:
            bounds = [
                Fraction(value.replace("−", "-").replace(",", "."))
                for value in interval_match.groups()
            ]
        except (ValueError, ZeroDivisionError):
            continue
        option_text = [str(option).strip() for option in sample.get("options", [])]
        numeric_choice_set = bool(option_text) and all(
            re.fullmatch(r"[−-]?\d+(?:[,.]\d+)?(?:/\d+)?", option) for option in option_text
        )
        answer_text = str(sample.get("answer", "")).strip()
        numeric_answer = bool(re.fullmatch(r"[−-]?\d+(?:[,.]\d+)?(?:/\d+)?", answer_text))
        option_values = [_numeric_values(option) for option in option_text]
        correct = _numeric_values(answer_text)
        if (
            numeric_choice_set
            and numeric_answer
            and len(bounds) == 2
            and correct
            and correct[0] in bounds
        ):
            wrong = [values[0] for values in option_values if values and values[0] not in correct]
            if (
                wrong  # noqa: E501
                and correct[0] in bounds
                and all(value < bounds[0] or value > bounds[1] for value in wrong)
            ):
                suspicious.append(int(sample["seed"]))
        answer_match = re.fullmatch(r"\s*√\s*(\d+)\s*", str(sample.get("answer", "")))
        if answer_match and len(bounds) == 2:
            radicand = int(answer_match.group(1))
            root = int(radicand**0.5)
            if root * root == radicand and Fraction(root) in bounds:  # noqa: E501
                perfect_square_endpoint.append(int(sample["seed"]))
    if suspicious:
        signal(
            "correct_interval_endpoint_with_external_distractors",
            "Correct numeric answer is an interval endpoint while numeric distractors are all outside",  # noqa: E501
            suspicious,
        )
        review_items.append(
            "inspect whether the choice can be selected without the intended comparison"
        )
    if perfect_square_endpoint:
        preferred: list[int] = []
        other: list[int] = []
        for seed in perfect_square_endpoint:
            sample = next(item for item in samples if int(item["seed"]) == seed)
            answer_match = re.fullmatch(r"\s*√\s*(\d+)\s*", str(sample.get("answer", "")))
            interval_match = interval_pattern.search(str(sample.get("condition", "")))
            if answer_match is None or interval_match is None:
                other.append(seed)
                continue
            root = int(int(answer_match.group(1)) ** 0.5)
            upper = Fraction(interval_match.group(2).replace("−", "-").replace(",", "."))
            (preferred if root > 1 and Fraction(root) == upper else other).append(seed)
        signal(
            "perfect_square_radical_at_interval_endpoint",
            "Correct radical simplifies to a perfect-square endpoint; competing radicals can be screened by rough magnitude",  # noqa: E501
            preferred + other,
        )
        review_items.append("compare radical distractors with the intended source comparison")

    duplicate_option_seeds: list[int] = []
    same_answer_option_seeds: list[int] = []
    implausible_distance_seeds: list[int] = []
    for sample in samples:
        options = [str(value).strip() for value in sample.get("options", [])]
        if options and len(options) != len(set(options)):
            duplicate_option_seeds.append(int(sample["seed"]))
        answer = str(sample.get("answer", "")).strip()
        if options and options.count(answer) > 1:
            same_answer_option_seeds.append(int(sample["seed"]))
        correct_values = _numeric_values(answer)
        wrong_values = [
            value for option in options if option != answer for value in _numeric_values(option)
        ]
        if correct_values and len(wrong_values) >= 2:  # noqa: E501
            correct_abs = abs(correct_values[0])
            if correct_abs and all(abs(value) > correct_abs * 20 for value in wrong_values):
                implausible_distance_seeds.append(int(sample["seed"]))
    if duplicate_option_seeds or same_answer_option_seeds:
        signal(
            "duplicate_or_key_repeated_choice",
            "Choice set contains duplicate strings or repeats the keyed answer",
            duplicate_option_seeds + same_answer_option_seeds,
        )
        review_items.append("check answer-choice uniqueness and the displayed key")
    if implausible_distance_seeds:
        signal(
            "numeric_distractors_much_farther_than_answer",
            "All numeric distractors are over 20× the absolute keyed answer; heuristic needs contextual review",  # noqa: E501
            implausible_distance_seeds,
        )
        review_items.append("assess distractor plausibility in the mathematical context")

    answer_positions = [  # noqa: E501
        int(sample["correct_option_position"])
        for sample in samples
        if sample.get("correct_option_position") is not None
    ]  # noqa: E501
    if len(answer_positions) >= 30:
        position_counts = Counter(answer_positions)
        dominant_position, dominant_count = position_counts.most_common(1)[0]
        if dominant_count / len(answer_positions) >= 0.7:
            signal(
                "correct_choice_position_skew",
                f"Position {dominant_position} holds {dominant_count}/{len(answer_positions)} keys; check whether option order leaks answers",  # noqa: E501
                [
                    int(sample["seed"])
                    for sample in samples
                    if sample.get("correct_option_position") == dominant_position
                ],
            )
            review_items.append("review answer-position balance and choice ordering")

    visible_types = Counter(
        "fraction" if "/" in token else "decimal" if "," in token or "." in token else "integer"
        for sample in samples
        for token in _numeric_tokens(str(sample.get("question_text", sample.get("condition", ""))))
    )
    if len(visible_types) == 1 and count >= 30:  # noqa: E501
        signal(
            "visible_number_type_is_uniform",
            f"All visible numeric tokens in the sample are {next(iter(visible_types))}",
            [int(sample["seed"]) for sample in samples],
        )  # noqa: E501
        review_items.append("check whether the prototype supports only this number type")

    # Visible-data leakage trigger for story tasks: compare requested value and
    # question context. The runtime's image/text presentation must be reviewed.
    if scenario:
        for sample in samples:
            context = str(sample.get("displayed_shared_context", sample.get("condition", "")))
            question = str(sample.get("question_text", ""))
            requested = re.search(r"(?:найдите|определите)\s+([^,.!?]+)", question, re.I)
            if (
                requested
                and re.search(r"\bA0\b", requested.group(1), re.I)
                and re.search(r"A0\s*[:—-]?\s*\d{3,4}\s*[×x]\s*\d{3,4}", context, re.I)
            ):
                signal(
                    "requested_value_appears_in_serialized_context",
                    "Question requests A0 width and raw serialized context includes labeled A0 dimensions",  # noqa: E501
                    [int(sample["seed"])],
                )
                review_items.append(
                    "verify actual Telegram display assets; serialized context may not be shown verbatim"  # noqa: E501
                )
                break
        disclosed_seeds: list[int] = []
        disclosed_examples: dict[int, dict[str, Any]] = {}
        for sample in samples:
            question = str(sample.get("question_text", ""))
            context_model = sample.get("scenario_context", {})
            target = re.search(r"формата\s+(A\d)", question, re.I)
            asks_dimension = bool(
                re.search(
                    r"(?:найдите|определите)\s+(?:ширину|длину)\s+(?:листа|бумаги)", question, re.I
                )
            )
            asks_rounding = bool(re.search(r"округл", question, re.I))
            if not asks_dimension or not asks_rounding:
                continue
            side = "long" if re.search(r"длинн", question, re.I) else "short"
            rows = context_model.get("rows", []) if isinstance(context_model, dict) else []
            if target is None:
                continue
            for visible_row in rows:
                if not isinstance(visible_row, list | tuple) or len(visible_row) < 3:
                    continue
                label = str(visible_row[0]).upper()
                value = visible_row[1] if side == "long" else visible_row[2]
                if label == target.group(1).upper():
                    disclosed_seeds.append(int(sample["seed"]))
                    disclosed_examples[int(sample["seed"])] = {
                        **sample,
                        "visible_requested_input": {
                            "format": label,
                            "side": side,
                            "value_mm": value,
                        },
                    }
                    break
        if disclosed_seeds:
            signal(
                "requested_measurement_disclosed_in_labeled_shared_table",
                "The visible shared table contains the requested format and measurement; the task then only applies its rounding instruction",  # noqa: E501
                disclosed_seeds,
            )
            for signal_row in signals:
                if signal_row["code"] == "requested_measurement_disclosed_in_labeled_shared_table":
                    signal_row["examples"] = [
                        disclosed_examples[seed] for seed in disclosed_seeds[:5]
                    ]
            review_items.append(
                "verify whether the visible table supplies the target quantity directly"
            )

    source_meta = row.get("source_evidence", {})
    source_text = _stable(source_meta) if isinstance(source_meta, dict) else str(source_meta)
    actual_text = " ".join(
        str(sample.get("question_text", sample.get("condition", "")))
        + " "
        + _stable(sample.get("solution", ""))
        for sample in samples[:5]
    )
    expected_concepts = _operation_concepts(source_text)
    generated_concepts = _operation_concepts(actual_text)
    if (
        expected_concepts
        and generated_concepts
        and expected_concepts.isdisjoint(generated_concepts)
    ):
        signal(
            "prototype_operation_vocabulary_mismatch",
            f"Source metadata concepts {sorted(expected_concepts)} do not overlap sampled task concepts {sorted(generated_concepts)}",  # noqa: E501
            [int(s.get("seed", 0)) for s in samples[:5]],
        )
        review_items.append(
            "manually compare generated operation with the cited prototype; vocabulary mismatch may be a false alarm"  # noqa: E501
        )

    # Uniform baseline for all runtime families. Source-fidelity can't be
    # inferred from generator success, so unverified cases remain explicit.
    source = row.get("source_evidence", {})
    source_status = (
        source.get("evidence_status", source.get("status", "")) if isinstance(source, dict) else ""
    )
    source_claims = bool(
        row.get("source_ids") or _reference_source_ids(source if isinstance(source, dict) else {})
    )
    review_items.extend(
        [
            "compare at least five examples with cited source structure",
            "review wording, answer format, hints and solution for sampled extremes",
        ]
    )
    cosmetic_by_math: dict[tuple[str, str], set[str]] = {}
    for key, sample in zip(keys, samples, strict=True):
        cosmetic_by_math.setdefault(
            (key["significant_parameters"], str(sample.get("answer", ""))), set()
        ).add(" ".join(str(sample.get("question_text", sample.get("condition", ""))).split()))
    cosmetic_only_variant_groups = sum(
        len(texts) - 1 for texts in cosmetic_by_math.values() if len(texts) > 1
    )
    historical = _historical_story_diversity().get(family_id) if scenario else None
    return {
        "sample_count": count,
        "example_review": {
            "status": "sampled_with_internal_oracle; manual source/content review incomplete",
            "examples_selected": min(5, count),
            "seeds": [sample.get("seed") for sample in samples[:5]],
            "internal_oracle_pass_count": sum(
                bool(sample.get("valid_oracle")) for sample in samples[:5]
            ),
            "source_comparison_status": "prior_review_available"
            if (scenario or row.get("source_ids"))
            else "unverified",
            "source_evidence_status": source_status
            or (
                "source IDs present; source text not independently opened"
                if source_claims
                else "missing source evidence"
            ),
            "manual_review_complete": False,
            "unreviewed_parts": [
                "independent source-text verification",
                "distractor pedagogical quality",
                "hint/explanation completeness",
            ],
        },
        "diversity": {
            "sample_count": count,
            "unique_full_story": len(set(story_keys)) if scenario else None,
            "unique_question_conditions": len(set(question_conditions)),
            "unique_significant_math_parameters": len(set(math_parameters)),
            "unique_answers": len(set(answers)),
            "cosmetic_presentation_variants": len(set(cosmetic)),
            "cosmetic_only_variants_with_same_math_and_answer": cosmetic_only_variant_groups,
            "question_condition_repeat_rate": round(repeat_rate, 4),
            "answer_distribution": dict(answer_counts.most_common(10)),
            "context_variation_not_counted_as_question_diversity": True,
            "prior_64_seed_report": historical,
            "comparison_note": (
                "Prior report used 64 issued questions and its full-story/signature metric. "
                "Current 50 examples are split into question text and question math parameters; "
                "counts are directional, not a same-seed delta."
                if historical
                else None
            ),
        },
        "detected_signals": signals,
        "confirmed_findings": [],
        "requires_manual_review": list(dict.fromkeys(review_items)),
        "diagnostic_status": "sampled; manual review incomplete",
    }


def _summarize(
    number: int, family: str, records: list[dict[str, Any]], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    conditions = [" ".join(row["condition"].split()) for row in records]
    display_content = [
        json.dumps(
            [
                condition,
                row.get("options", []),
                row.get("image_sha256", row.get("asset_sha256", [])),
                row.get("construction_signature"),
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        for condition, row in zip(conditions, records, strict=True)
    ]
    answers = [row["answer"] for row in records]
    fps = [row["fingerprint"] for row in records if row["fingerprint"]]
    signatures = [
        json.dumps(row["construction_signature"], ensure_ascii=False, sort_keys=True)
        for row in records
    ]
    duplicate_count = len(display_content) - len(set(display_content))
    text_duplicate_count = len(conditions) - len(set(conditions))
    numeric = [token for condition in conditions for token in _numeric_tokens(condition)]
    parameter_values: dict[str, list[float]] = {}
    for row in records:
        for path, value in _parameter_numbers(row.get("construction_parameters")):
            parameter_values.setdefault(path, []).append(value)
    number_types = Counter(
        "fraction" if "/" in x else "decimal" if "," in x or "." in x else "integer"
        for x in numeric
    )
    record = {
        "sample_count": len(records),
        "seeds": [row["seed"] for row in records],
        "unique_conditions": len(set(display_content)),
        "unique_condition_texts": len(set(conditions)),
        "condition_repeat_count": duplicate_count,
        "condition_repeat_rate": round(duplicate_count / len(records), 4) if records else None,
        "identical_condition_text_count": text_duplicate_count,
        "unique_answers": len(set(answers)),
        "answer_distribution": dict(Counter(answers).most_common(15)),
        "unique_fingerprints": len(set(fps)),
        "unique_construction_signatures": len(set(signatures)),
        "visible_number_token_types": dict(number_types),
        "visible_number_min": min(
            (float(x.replace("−", "-").replace(",", ".")) for x in numeric if "/" not in x),
            default=None,
        ),
        "visible_number_max": max(
            (float(x.replace("−", "-").replace(",", ".")) for x in numeric if "/" not in x),
            default=None,
        ),
        "parameter_distributions": {
            path: {
                "sampled_values": len(values),
                "unique_values": len(set(values)),
                "minimum": min(values),
                "maximum": max(values),
                "most_common": Counter(values).most_common(10),
            }
            for path, values in parameter_values.items()
        },
        "oracle_failures": failures,
        "generation_failure_count": sum(
            item.get("failure_kind") == "generation_error" for item in failures
        ),
        "oracle_rejection_count": sum(
            item.get("failure_kind") == "oracle_false" for item in failures
        ),
        "representative_examples": records[:5],
        "samples": records,
        "method_complexity": _complexity(number, family, records[:5]),
        "max_condition_characters": max((len(row["condition"]) for row in records), default=0),
    }
    option_samples = [row["options"] for row in records if row["options"]]
    if option_samples:
        record["option_count_distribution"] = dict(Counter(map(len, option_samples)))
        record["option_unique_values_by_position"] = [
            len({options[index] for options in option_samples if len(options) > index})
            for index in range(max(map(len, option_samples)))
        ]
        record["duplicate_option_sets"] = sum(
            len(opts) != len(set(opts)) for opts in option_samples
        )
        record["correct_option_position_distribution"] = dict(
            Counter(
                row["correct_option_position"]
                for row in records
                if row.get("correct_option_position") is not None
            )
        )
    return record


def _family_audit(number: int, family: str, sample_size: int) -> tuple[dict[str, Any], list[Any]]:
    families, make = _ordinary_generator(number)
    if family not in families:
        raise ValueError(f"Family {family} is not runtime-enabled for task {number}")
    records: list[dict[str, Any]] = []
    preview_items: list[Any] = []
    failures: list[dict[str, Any]] = []
    for seed in _seed_sequence(number, family, sample_size):
        try:
            problem = make(family, seed)
            valid = _oracle(number, family, problem)
            record = _sample_record(problem, number, seed, valid)
            records.append(record)
            preview_items.append(problem)
            if not valid:
                failures.append(
                    {
                        "seed": seed,
                        "failure_kind": "oracle_false",
                        "reason": "independent oracle returned false",
                    }
                )
        except Exception as error:  # record the failing seed and continue the family audit
            failures.append(
                {
                    "seed": seed,
                    "failure_kind": "generation_error",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
    summary = _summarize(number, family, records, failures)
    if family == "OGE07-C04":
        boundary_examples = []
        integer_targets = 0
        boundary_answers = 0
        for row in records:
            interval = re.search(r"\[([^;]+); ([^]]+)\]", row["condition"])
            if interval is None:
                continue
            target = Fraction(row["answer"].replace("−", "-").replace(",", "."))
            endpoints = tuple(
                Fraction(value.replace("−", "-").replace(",", ".")) for value in interval.groups()
            )
            integer_targets += target.denominator == 1
            if target in endpoints:
                boundary_answers += 1
                if len(boundary_examples) < 10:
                    boundary_examples.append(row)
        summary["integer_target_count"] = integer_targets
        summary["integer_target_rate"] = round(integer_targets / len(records), 4)
        summary["integer_boundary_answer_count"] = boundary_answers
        summary["integer_boundary_answer_rate"] = round(boundary_answers / len(records), 4)
        summary["integer_boundary_examples"] = boundary_examples
        summary["source_comparison"] = {
            "source_id": "369728",
            "source_prototype": "68/19 принадлежит [3;4]",
            "generated_target_domain": (
                "denominators 2, 3, 4, 5, or 10; finite decimals in the displayed options"
            ),
        }
    return summary, preview_items


def _representative_samples(
    row: dict[str, Any], signals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    samples = row.get("samples", [])
    if len(samples) <= 5:
        return samples
    chosen: list[dict[str, Any]] = []

    def add(sample: dict[str, Any] | None) -> None:
        if sample is not None and all(sample.get("seed") != item.get("seed") for item in chosen):
            chosen.append(sample)

    add(samples[0])
    add(samples[len(samples) // 2])
    add(samples[-1])
    suspicious = {seed for item in signals for seed in item.get("seeds", [])}
    for sample in samples:
        if sample.get("seed") in suspicious:
            add(sample)
            break
    answer_values: list[tuple[Fraction, dict[str, Any]]] = []
    for sample in samples:
        try:
            value = Fraction(str(sample.get("answer", "")).replace("−", "-").replace(",", "."))
        except (ValueError, ZeroDivisionError):
            continue
        answer_values.append((value, sample))
    if answer_values:
        add(min(answer_values, key=lambda item: item[0])[1])
        add(max(answer_values, key=lambda item: item[0])[1])
    for sample in samples:
        if len(chosen) >= 5:
            break
        add(sample)
    return chosen[:5]


# noqa: E501
# noqa: E501
def _sample_content_checks(samples: list[dict[str, Any]]) -> dict[str, Any]:  # noqa: E501
    def present(value: Any) -> bool:  # noqa: E501
        return bool(value) and (not isinstance(value, str) or bool(value.strip()))  # noqa: E501

    # noqa: E501
    missing_condition = [  # noqa: E501
        s.get("seed")
        for s in samples
        if not present(s.get("question_text", s.get("condition")))  # noqa: E501
    ]
    missing_answer = [s.get("seed") for s in samples if not present(s.get("answer"))]
    missing_hints = [s.get("seed") for s in samples if not present(s.get("hints"))]
    missing_solution = [s.get("seed") for s in samples if not present(s.get("solution"))]
    answer_in_hint = []
    duplicate_options = []
    for sample in samples:
        answer = str(sample.get("answer", "")).strip()
        hints = " ".join(map(str, sample.get("hints", [])))
        if answer and re.search(rf"(?<!\w){re.escape(answer)}(?!\w)", hints):
            answer_in_hint.append(sample.get("seed"))
        options = list(map(str, sample.get("options", [])))
        if len(options) != len(set(options)):
            duplicate_options.append(sample.get("seed"))
    return {
        "examples_checked": len(samples),
        "oracle_pass_count": sum(bool(s.get("valid_oracle")) for s in samples),
        "missing_condition_seeds": missing_condition,
        "missing_answer_seeds": missing_answer,  # noqa: E501
        "missing_hint_seeds": missing_hints,
        "missing_solution_seeds": missing_solution,
        "answer_repeated_verbatim_in_hint_seeds": answer_in_hint,
        "duplicate_option_seeds": duplicate_options,
        "status": "automated_example_checks_complete"
        if len(samples) >= 5
        else "insufficient_examples",
        "limits": [
            "Static checks do not prove source fidelity or educational clarity.",
            "Distractor usefulness and explanation pedagogy require expert interpretation.",
        ],
    }


def _compact_sample(sample: dict[str, Any]) -> dict[str, Any]:  # noqa: E501
    """Keep reproducible evidence without duplicating entire story snapshots."""
    fields_to_keep = (
        "seed",
        "scenario_seed",
        "family_id",
        "position",
        "valid_oracle",
        "question_text",
        "condition",
        "answer",
        "options",
        "correct_option_position",
        "hints",
        "solution",
        "construction_parameters",
        "source_ids",
        "fingerprint",
        "image_sha256",
        "visible_requested_input",
    )
    result = {key: _jsonable(sample[key]) for key in fields_to_keep if key in sample}
    if "question_text" in result:
        result.pop("condition", None)
    return result


def _confirmed_findings(families: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Promote reproducible, evidence-backed findings; retain heuristics as signals."""
    findings: list[dict[str, Any]] = []
    endpoint_codes = {
        "correct_interval_endpoint_with_external_distractors",
        "perfect_square_radical_at_interval_endpoint",
    }
    for family_id, row in families.items():
        signals = row.get("quality_diagnostics", {}).get("detected_signals", [])
        corroborated = [
            item
            for item in signals
            if item["code"] == "requested_measurement_disclosed_in_labeled_shared_table"
            or item["code"] in endpoint_codes
        ]
        # The two interval heuristics can describe the same defect. Keep one
        # representative from each mathematical family, preferring the radical
        # signal where the task is a radical comparison.
        endpoint = next(
            (
                item
                for item in corroborated
                if item["code"] == "perfect_square_radical_at_interval_endpoint"
            ),
            None,
        ) or next((item for item in corroborated if item["code"] in endpoint_codes), None)
        direct = next(
            (
                item
                for item in corroborated
                if item["code"] == "requested_measurement_disclosed_in_labeled_shared_table"
            ),
            None,
        )
        for detected in [item for item in (endpoint, direct) if item is not None]:
            if not detected.get("examples"):
                continue
            sample = detected["examples"][0]
            direct_disclosure = (
                detected["code"] == "requested_measurement_disclosed_in_labeled_shared_table"
            )
            explanation = (
                "Подписанная PNG-таблица общего сюжета уже показывает запрошенную величину "
                f"{sample.get('visible_requested_input')}; ученик затем округляет её до "
                f"`{sample.get('answer')}`. "
                "Предыдущая матрица источника ожидала таблицу без подписей форматов, "
                "чтобы нужную строку требовалось вывести."
                if direct_disclosure
                else (
                    "Правильный вариант упрощается до целого конца интервала, а отвлекающие "
                    "варианты по величине отсекаются без сравнения радикалов/чисел. Это "
                    "существенно проще проверенных источниковых примеров."
                )
            )
            recommendation = (
                "Для этого вопроса отрисовывать таблицу без названий форматов, как в "
                "проверенной структуре источника; оставить oracle, проверяющий вывод нужной строки."
                if direct_disclosure
                else (
                    "Исключить точные целые/граничные корни; строить варианты, требующие "
                    "сравнения с обеими границами, и проверять отвлекающие варианты "
                    "независимым oracle."
                )
            )
            findings.append(
                {
                    "id": f"{family_id}-VISIBLE-TARGET-DATA"
                    if direct_disclosure
                    else f"{family_id}-TRIVIAL-ENDPOINT",
                    "priority": "P1",
                    "family_id": family_id,
                    "status": "confirmed_finding",
                    "seed": sample.get("seed"),
                    "condition": sample.get("question_text", sample.get("condition", "")),
                    "answer": sample.get("answer", ""),
                    "options": sample.get("options", []),
                    "expected_behavior": (
                        "Ученик выполняет математическую операцию, предусмотренную "
                        "подтверждённым прототипом."
                    ),
                    "actual_behavior": explanation,
                    "explanation": explanation,
                    "recommended_fix": recommendation,
                    "sample_size": row.get("sample_count"),
                    "signal_count": detected.get("signal_count"),
                    "signal_rate": detected.get("signal_rate"),
                    "source_ids": row.get("source_ids", []),
                    "student_block_required": False,
                }
            )

    # This finding is generated from measured family statistics, never an ID list.
    # It confirms the objective lack of observed question-level variety; whether
    # this is pedagogically unsuitable still needs explicit manual review.
    for family_id, row in families.items():
        diagnostics = row.get("quality_diagnostics", {})
        diversity = diagnostics.get("diversity", {})
        signal_codes = {item.get("code") for item in diagnostics.get("detected_signals", [])}
        if "question_construction_collapsed_to_one_observed_case" not in signal_codes:
            continue
        sample = row.get("representative_examples", [{}])[0]
        findings.append(
            {
                "id": f"{family_id}-QUESTION-LEVEL-LOW-DIVERSITY",
                "priority": "P2",
                "family_id": family_id,
                "status": "confirmed_finding",
                "seed": sample.get("seed"),
                "condition": sample.get("question_text", sample.get("condition", "")),
                "answer": sample.get("answer", ""),
                "explanation": (
                    f"В {diversity.get('sample_count')} seed получены "
                    f"{diversity.get('unique_question_conditions')} условия, "
                    f"{diversity.get('unique_significant_math_parameters')} набора значимых "
                    f"параметров и {diversity.get('unique_answers')} ответа. Это подтверждает "
                    "узкое наблюдаемое разнообразие; приемлемость конечной ёмкости требует "
                    "отдельного решения методиста."
                ),
                "evidence": diversity,
                "recommended_fix": (
                    "Не считать вариацию общего сюжета новой математической задачей. "
                    "Ограничивать близкие повторы, а семейство расширять только новыми "
                    "проверенными источниковыми конструкциями; конечную ёмкость документировать."
                ),
                "source_ids": row.get("source_ids", []),
            }
        )
    return findings


def _scenario_audit() -> tuple[dict[str, Any], dict[str, Any]]:
    registry = public_registry()
    story_rows: dict[str, Any] = {}
    family_rows: dict[str, list[dict[str, Any]]] = {}
    preview_plans: dict[str, Any] = {}
    all_public = {family for ids in PUBLIC_FAMILIES.values() for family in ids}
    for story in sorted(PUBLIC_FAMILIES):
        counts: Counter[str] = Counter()
        failures: list[dict[str, Any]] = []
        plan_examples: dict[str, list[dict[str, Any]]] = {
            family: [] for family in PUBLIC_FAMILIES[story]
        }
        best_plan = None
        best_score = -1
        for offset in range(SCENARIO_SEEDS):
            seed = SEED_NAMESPACE + 1_500_000 + offset
            try:
                plan = build_practice_plan(
                    PracticeRequest(PracticeMode.FULL, seed, story), registry
                )
            except Exception as error:
                failures.append({"seed": seed, "reason": f"{type(error).__name__}: {error}"})
                continue
            snapshot = plan.snapshot
            score = len(snapshot.shared_context) + sum(len(q.condition) for q in snapshot.questions)
            if score > best_score:
                best_plan, best_score = plan, score
            for question in snapshot.questions:
                family = question.family_id
                counts[family] += 1
                if family not in plan_examples:
                    continue
                qrow = question.to_snapshot()
                qrow["question_text"] = question.condition
                qrow["asset_sha256"] = [asset.sha256 for asset in snapshot.assets]
                qrow["bundle_provenance"] = list(snapshot.provenance)
                qrow["condition"] = f"{snapshot.shared_context}\n{question.condition}"
                qrow["displayed_shared_context"] = _scenario_display_context(snapshot)
                qrow["scenario_context"] = _jsonable(snapshot.context)
                qrow["full_story_fingerprint"] = hashlib.sha256(
                    _stable(
                        [
                            snapshot.story_code,
                            snapshot.shared_context,
                            [asset.sha256 for asset in snapshot.assets],
                            snapshot.context,
                        ]
                    ).encode()
                ).hexdigest()
                qrow.update(
                    {
                        "seed": seed,
                        "valid_oracle": True,
                        "answer": question.canonical_answer,
                        "options": [],
                        "solution": _jsonable(question.solution_steps),
                        "construction_signature": _jsonable(_shape(_jsonable(question.math_model))),
                        "construction_parameters": _jsonable(question.math_model),
                        "fingerprint": hashlib.sha256(
                            json.dumps(
                                [
                                    story,
                                    snapshot.context,
                                    [a.sha256 for a in snapshot.assets],
                                    question.condition,
                                    question.math_model,
                                ],
                                ensure_ascii=False,
                                sort_keys=True,
                                default=str,
                            ).encode()
                        ).hexdigest(),
                    }
                )
                max_examples = 300 if family in EXTENDED_SCENARIO_FAMILIES else SAMPLE_SEEDS
                if len(plan_examples[family]) < max_examples:
                    plan_examples[family].append(qrow)
        registrations = {row.family_id: row for row in registry.adapter(story).family_registry}
        for family in sorted(PUBLIC_FAMILIES[story]):
            rows = plan_examples[family]
            reg = registrations[family]
            family_rows[family] = rows
            summary = _summarize(1, family, rows, failures)
            summary["method_complexity"] = {
                "score": SCENARIO_COMPLEXITY.get(family, 3),
                "rationale": (
                    "Оценка основана на операции и пяти фиксированных условиях из примеров; "
                    "число шагов, выбор данных из таблиц/схем и общий сюжет учтены отдельно."
                ),
                "reviewed_example_seed": rows[0].get("seed") if rows else None,
            }
            summary.update(
                {
                    "exam_number": "1-5",
                    "story": story,
                    "position": reg.position,
                    "runtime_status": reg.status.value,
                    "enabled_for_students": reg.available,
                    "source_ids": list(reg.source_ids),
                    "source_evidence": _atlas_evidence(family),
                }
            )
        story_rows[story] = {
            "bundle_count_requested": SCENARIO_SEEDS,
            "bundle_count_passed": SCENARIO_SEEDS - len(failures),
            "family_occurrence_counts": dict(counts),
            "families_with_50_examples": sum(
                len(rows) >= SAMPLE_SEEDS for rows in plan_examples.values()
            ),
            "family_count": len(PUBLIC_FAMILIES[story]),
            "bundle_oracle_failures": failures,
            "representative_full_bundle_seed": best_plan.snapshot.seed if best_plan else None,
            "representative_full_bundle": best_plan.snapshot.to_snapshot() if best_plan else None,
        }
        if best_plan:
            preview_plans[story] = best_plan.snapshot
    if set(family_rows) != all_public:
        raise RuntimeError("Public scenario audit did not cover the runtime allowlist")
    return {"stories": story_rows, "families": family_rows}, preview_plans


def _registry_reference_rows() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "atlas").glob("oge*_reference_structures.json")):
        data = json.loads(path.read_text(encoding="utf-8"))

        def visit(value: Any, source_file: Path = path) -> None:
            if isinstance(value, dict):
                family_id = value.get("family_id", value.get("id"))
                if isinstance(family_id, str):
                    rows[family_id] = {
                        key: value[key]
                        for key in (
                            "name",
                            "label",
                            "title",
                            "status",
                            "source_status",
                            "reason",
                            "status_reason",
                            "specific_caution",
                            "notes",
                            "implementation_status",
                            "implementation_reason",
                            "admission_note",
                            "source_ids",
                            "source_case_ids",
                            "reference_ids",
                            "ids",
                            "prototype_ids",
                            "urls",
                            "source_urls",
                            "source_url",
                            "sources",
                            "source_type",
                            "manual_difficulty",
                            "difficulty",
                            "mathematical_shape",
                            "construction_description",
                            "distractor_types",
                            "parameter_contract",
                            "answer_policy",
                            "examples",
                            "structure",
                            "generator",
                            "ranges",
                            "complexity",
                            "answer_format",
                        )
                        if key in value
                    }
                    rows[family_id]["reference_file"] = str(source_file.relative_to(ROOT))
                for child in value.values():
                    visit(child, source_file)
            elif isinstance(value, list):
                for child in value:
                    visit(child, source_file)

        visit(data)
        if path.name == "oge6_reference_structures.json":
            from app.math.registry import GENERATOR_SPECS

            for spec in GENERATOR_SPECS:
                reference = rows.get(spec.reference_structure_id, {})
                rows[spec.family_id] = {
                    **reference,
                    "reference_structure_id": spec.reference_structure_id,
                    "source_ids": list(spec.source_ids),
                    "reference_file": str(path.relative_to(ROOT)),
                }
    return rows


def _story_coverage_lines() -> dict[str, tuple[str, list[str]]]:
    paths = {
        "FLAT": "reports/oge15-flat-coverage.md",
        "GARDEN": "reports/oge15-garden-coverage.md",
        "PAPER": "specs/coverage/OGE15_PAPER_COVERAGE.md",
        "ROUTE": "reports/oge15-route-coverage.md",
        "STOVE": "reports/oge15-stove-coverage.md",
        "TARIFF": "reports/oge15-tariff-coverage.md",
        "TYRES": "reports/oge15-tyres-coverage.md",
    }
    result: dict[str, tuple[str, list[str]]] = {}
    for story, file in paths.items():
        path = ROOT / file
        if not path.exists():
            continue
        result[story] = (
            file,
            [line.strip() for line in path.read_text(encoding="utf-8").splitlines()],
        )
    return result


def _disabled_inventory() -> list[dict[str, Any]]:
    atlas = json.loads((ROOT / "atlas" / "families.json").read_text(encoding="utf-8"))
    by_id = {item.get("id"): item for item in atlas if isinstance(item, dict)}
    references = _registry_reference_rows()
    story_coverage = _story_coverage_lines()
    rows: list[dict[str, Any]] = []
    registry = public_registry()
    for story in registry.story_codes:
        enabled = set(PUBLIC_FAMILIES.get(story, ()))
        for item in registry.adapter(story).family_registry:
            if item.family_id not in enabled:
                coverage_file, coverage_lines = story_coverage.get(story, (None, []))
                coverage_row = next(
                    (line for line in coverage_lines if item.family_id in line), None
                )
                ref = references.get(item.family_id, {})
                entry = by_id.get(item.family_id, {})
                reason = (
                    ref.get("status_reason")
                    or ref.get("reason")
                    or ref.get("specific_caution")
                    or ref.get("implementation_reason")
                    or ref.get("admission_note")
                    or ref.get("notes")
                    or entry.get("specific_caution")
                    or (coverage_row if coverage_file else None)
                    or entry.get("evidence_status")
                    or (
                        "Семейство отсутствует в публичном allowlist; "
                        "в изученных reference-файлах отдельная причина не указана."
                    )
                )
                rows.append(
                    {
                        "family_id": item.family_id,
                        "exam_number": 1,
                        "story": story,
                        "runtime_status": item.status.value,
                        "atlas_status": entry.get("evidence_status") or ref.get("status"),
                        "source_ids": list(item.source_ids),
                        "reason": reason,
                        "reference_file": ref.get("reference_file"),
                        "coverage_file": coverage_file,
                        "coverage_row": coverage_row,
                    }
                )
    module_specs = [
        (6, "app.math.registry", "GENERATOR_SPECS", "SPEC_BY_ID"),
        (7, "app.math.oge07_scheduler", "ALL_FAMILIES", "ENABLED_FAMILIES"),
        (8, "app.math.oge8", "ALL_FAMILIES", "ENABLED_FAMILIES"),
        (11, "app.math.oge11", "FAMILIES", "ENABLED_FAMILIES"),
        (12, "app.math.formulas", "ALL_FAMILIES", "ENABLED_FAMILIES"),
        (13, "app.math.inequalities", "ALL_FAMILIES", "ENABLED_FAMILIES"),
        (14, "app.math.progressions", "ALL_FAMILIES", "ENABLED_FAMILIES"),
    ]
    for number, module_name, all_name, enabled_name in module_specs:
        module = importlib.import_module(module_name)
        enabled = set(getattr(module, enabled_name, ()))
        all_values = getattr(module, all_name)
        ids = [value.family_id for value in all_values] if number == 6 else all_values
        for family in ids:
            if family not in enabled:
                entry = by_id.get(family, {})
                ref = references.get(family, {})
                reason = (
                    ref.get("status_reason")
                    or ref.get("reason")
                    or ref.get("specific_caution")
                    or ref.get("implementation_reason")
                    or ref.get("admission_note")
                    or ref.get("notes")
                    or entry.get("specific_caution")
                    or entry.get("evidence_status")
                    or (
                        "Семейство отмечено в атласе, но отсутствует в runtime allowlist; "
                        "отдельная причина в изученных reference-файлах не указана."
                    )
                )
                rows.append(
                    {
                        "family_id": family,
                        "exam_number": number,
                        "runtime_status": getattr(module, "FAMILY_STATUS", {}).get(
                            family, "disabled"
                        ),
                        "atlas_status": entry.get("evidence_status"),
                        "source_ids": entry.get("verified_example_ids", []),
                        "reason": reason,
                        "reference_file": ref.get("reference_file"),
                    }
                )
    for number in (9, 10):
        enabled = set(
            importlib.import_module(
                "app.math.equations" if number == 9 else "app.math.probability"
            ).ENABLED_FAMILIES
        )
        for entry in atlas:
            if entry.get("number") == number and entry.get("id") not in enabled:
                ref = references.get(entry.get("id"), {})
                reason = (
                    ref.get("status_reason")
                    or ref.get("reason")
                    or ref.get("specific_caution")
                    or ref.get("implementation_reason")
                    or ref.get("admission_note")
                    or ref.get("notes")
                    or entry.get("specific_caution")
                    or entry.get("evidence_status")
                    or "Не входит в enabled family registry."
                )
                rows.append(
                    {
                        "family_id": entry.get("id"),
                        "exam_number": number,
                        "runtime_status": "not_enabled_in_generator_registry",
                        "atlas_status": entry.get("evidence_status"),
                        "source_ids": entry.get("verified_example_ids", []),
                        "reason": reason,
                        "reference_file": ref.get("reference_file"),
                    }
                )
    return rows


def _scheduler_builder(number: int) -> Callable[[dict[str, Any], int], list[dict[str, Any]]]:
    paths = {
        6: ("app.math.scheduler", "build_candidate_batch"),
        7: ("app.math.oge07_scheduler", "build_task7_candidate_batch"),
        8: ("app.math.oge8_scheduler", "build_task8_candidate_batch"),
        9: ("app.math.oge9_scheduler", "build_task9_candidate_batch"),
        10: ("app.math.oge10_scheduler", "build_task10_candidate_batch"),
        11: ("app.math.oge11_scheduler", "build_task11_candidate_batch"),
        12: ("app.math.oge12_scheduler", "build_task12_candidate_batch"),
        13: ("app.math.oge13_scheduler", "build_task13_candidate_batch"),
        14: ("app.math.oge14_scheduler", "build_task14_candidate_batch"),
    }
    module_name, function_name = paths[number]
    return getattr(importlib.import_module(module_name), function_name)


def _sequence_audit() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for number in range(6, 15):
        builder = _scheduler_builder(number)
        state: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        for index in range(20):
            batch = builder(state, SEED_NAMESPACE + number * 10_000 + index)
            if not batch:
                rows.append({"issuance": index + 1, "failure": "empty candidate batch"})
                continue
            item = batch[0]
            family = str(item.get("family_id", ""))
            fingerprint = str(item.get("fingerprint", ""))
            state["family_queue"] = item.get("_family_queue_after", [])
            transition_keys = {
                "_last_family_after": "last_family_id",
                "_last_group_after": "last_group",
                "_group_run_length_after": "group_run_length",
            }
            for source, target in transition_keys.items():
                if source in item:
                    state[target] = item[source]
            recent = list(state.get("recent_fingerprints", []))
            if fingerprint:
                recent.append(fingerprint)
            state["recent_fingerprints"] = recent[-30:]
            rows.append(
                {
                    "issuance": index + 1,
                    "seed": item.get("seed"),
                    "family_id": family,
                    "fingerprint": fingerprint,
                    "condition": item.get("condition", item.get("equation_text", "")),
                    "answer": item.get("correct_answer", ""),
                    "options": item.get("options", []),
                }
            )
        families = [str(row.get("family_id", "")) for row in rows]
        fps = [str(row.get("fingerprint", "")) for row in rows if row.get("fingerprint")]
        answers = [str(row.get("answer", "")) for row in rows]
        result[str(number)] = {
            "issuances": rows,
            "family_distribution": dict(Counter(families)),
            "adjacent_same_family": sum(
                a == b for a, b in zip(families, families[1:], strict=False)
            ),
            "longest_family_run": _longest_run(families),
            "repeated_fingerprints": len(fps) - len(set(fps)),
            "repeated_adjacent_answers": sum(
                a == b for a, b in zip(answers, answers[1:], strict=False)
            ),
        }
    registry = public_registry()
    scenario_rows = []
    for index in range(20):
        seed = SEED_NAMESPACE + index
        plan = build_practice_plan(PracticeRequest(PracticeMode.FULL, seed), registry)
        snapshot = plan.snapshot
        digest = hashlib.sha256(
            json.dumps(
                snapshot.to_snapshot(), ensure_ascii=False, sort_keys=True, default=str
            ).encode()
        ).hexdigest()
        scenario_rows.append(
            {
                "issuance": index + 1,
                "seed": seed,
                "story": snapshot.story_code,
                "family_ids": [question.family_id for question in snapshot.questions],
                "bundle_fingerprint": digest,
            }
        )
    story_codes = [row["story"] for row in scenario_rows]
    bundle_fingerprints = [row["bundle_fingerprint"] for row in scenario_rows]
    result["1-5"] = {
        "issuances": scenario_rows,
        "story_distribution": dict(Counter(story_codes)),
        "adjacent_same_story": sum(
            a == b for a, b in zip(story_codes, story_codes[1:], strict=False)
        ),
        "repeated_bundle_fingerprints": len(bundle_fingerprints) - len(set(bundle_fingerprints)),
        "note": (
            "Each issuance uses build_practice_plan(FULL) and the runtime story-selection "
            "registry; every bundle is independently validated."
        ),
    }
    return result


def _longest_run(values: list[str]) -> int:
    best = current = 0
    previous = None
    for item in values:
        current = current + 1 if item == previous else 1
        previous, best = item, max(best, current)
    return best


def _scenario_previews(plan_map: dict[str, Any]) -> list[str]:
    from app.bot.math_image import render_math_image
    from app.math.scenarios.mobile_photos import scenario_photos_for_question

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    outputs = []
    for story, snapshot in sorted(plan_map.items()):
        cards = []
        context = _scenario_display_context(snapshot)
        if context:
            cards.append(_mobile_card(render_math_image(f"Данные сюжета {story}\n\n{context}")))
        for question in snapshot.questions:
            images = scenario_photos_for_question(snapshot, question.position)
            for image in images:
                cards.append(_mobile_card(image))
            cards.append(
                _mobile_card(
                    render_math_image(
                        f"{story} · №{question.position} из 5\n\n"
                        f"{question.condition}\n\nНапишите ответ в чат."
                    )
                )
            )
        sheet = Image.new("RGB", (MOBILE_WIDTH, sum(card.height for card in cards)), "white")
        y = 0
        for card in cards:
            sheet.paste(card, (0, y))
            y += card.height
        name = f"oge15-{story.lower()}-mobile-390.png"
        sheet.save(ASSET_DIR / name, optimize=True)
        outputs.append(str((ASSET_DIR / name).relative_to(ROOT)))
    return outputs


def _mobile_card(image: bytes) -> Image.Image:
    from io import BytesIO

    with Image.open(BytesIO(image)) as opened:
        card = opened.convert("RGB")
        if card.width != MOBILE_WIDTH:
            card = card.resize((MOBILE_WIDTH, round(card.height * MOBILE_WIDTH / card.width)))
        return card.copy()


def _scenario_display_context(snapshot: Any) -> str:
    context = snapshot.shared_context
    question = next(
        item for item in snapshot.questions if item.position == snapshot.questions[0].position
    )
    if snapshot.story_code == "TYRES":
        context = "\n".join(line for line in context.splitlines() if not line.startswith("|"))
        context = context.replace("**", "")
    elif snapshot.story_code == "PAPER":
        context = context.partition("Таблица размеров")[0].rstrip()
    elif snapshot.story_code == "STOVE":
        context = context.partition("Печь | Тип |")[0].rstrip()
    elif snapshot.story_code == "TARIFF":
        context = "\n".join(
            line
            for line in context.splitlines()
            if not line.startswith(
                (
                    "На графике сплошная",
                    "Минуты по месяцам:",
                    "Мобильный интернет по месяцам:",
                )
            )
        )
        context += "\nМинуты и гигабайты показаны на отдельных графиках."
    elif snapshot.story_code == "GARDEN" and snapshot.generator_version in {
        "garden-sosnovka-1.0",
        "garden-sosnovka-1.1",
    }:
        context += (
            "\nДом с выступом у верхней границы. Баня ниже яблонь слева, "
            "гараж ниже ворот справа, теплица внутри огорода."
        )
    elif snapshot.story_code == "GARDEN" and question.family_id != "GARDEN-09-HEAT-BREAKEVEN":
        prefix, separator, remainder = context.partition("Отопление одного дома")
        if separator:
            _, shared_questions, closing = remainder.partition("Все пять вопросов")
            context = prefix + ("\nВсе пять вопросов" + closing if shared_questions else "")
    elif snapshot.story_code == "FLAT":
        context = context.replace("Это собственная SVG/PNG схема фиксированной топологии.", "")
        if "первая лоджия" in snapshot.questions[2].condition:
            context += " На плане первая лоджия расположена слева."
    return context


def _number_previews(number: int, previews: dict[int, dict[str, list[Any]]]) -> list[str]:
    from io import BytesIO

    from app.bot.math_image import render_math_image

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    cards = []
    for family, problems in sorted(previews[number].items()):
        if not problems:
            continue
        problem = max(problems, key=lambda p: len(_condition(p, number)))
        text = f"ОГЭ №{number} · {family}\n{_condition(problem, number)}"
        options = _options(problem)
        if options:
            text += "\n\n" + "\n".join(f"{i}. {option}" for i, option in enumerate(options, 1))
        diagram = getattr(problem, "png", getattr(problem, "png_bytes", None))
        if diagram is not None:
            png_bytes = render_math_image(text, diagram)
        else:
            png_bytes = render_math_image(text)
        with Image.open(BytesIO(png_bytes)) as opened:
            card = opened.convert("RGB")
            if card.width != MOBILE_WIDTH:
                card = card.resize((MOBILE_WIDTH, round(card.height * MOBILE_WIDTH / card.width)))
        cards.append(card)
    if not cards:
        return []
    sheet = Image.new("RGB", (MOBILE_WIDTH, sum(card.height for card in cards)), "white")
    y = 0
    for card in cards:
        sheet.paste(card, (0, y))
        y += card.height
    name = f"oge{number:02d}-families-mobile-390.png"
    sheet.save(ASSET_DIR / name, optimize=True)
    return [str((ASSET_DIR / name).relative_to(ROOT))]


def _quality_references() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for number, file in QUALITY_REPORTS.items():
        path = ROOT / file
        if not path.exists():
            continue
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            result[str(number)] = {
                "path": file,
                "report_sample_size": data.get(  # noqa: E501
                    "sample_count_per_family",
                    data.get("main_cases_per_family", data.get("sample_size_per_family")),
                ),
                "report_keys": list(data)[:12],
            }
        else:
            result[str(number)] = {
                "path": file,
                "format": "markdown",
                "headings": [
                    line.lstrip("# ")
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith("#")
                ][:12],
            }
    return result


def _atlas_evidence(family_id: str) -> dict[str, Any]:
    atlas = json.loads((ROOT / "atlas" / "families.json").read_text(encoding="utf-8"))
    entry = next((item for item in atlas if item.get("id") == family_id), {})
    return {
        key: entry[key]
        for key in (
            "name",
            "evidence_status",
            "verified_example_ids",
            "references",
            "generation_unit",
            "answer_format",
            "quality_criteria",  # noqa: E501
            "specific_caution",  # noqa: E501
        )
        if key in entry
    }


def _reference_source_ids(reference: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("source_ids", "source_case_ids", "reference_ids", "prototype_ids", "ids"):
        candidate = reference.get(key, [])  # noqa: E501
        if isinstance(candidate, list):
            values.extend(candidate)
    for key in ("sources", "examples"):
        sources = reference.get(key, [])
        if isinstance(sources, list):
            values.extend(
                item.get("task_id", item.get("id"))
                for item in sources
                if isinstance(item, dict) and item.get("task_id", item.get("id")) is not None
            )
    return list(dict.fromkeys(str(value) for value in values))


# noqa: E501
# noqa: E501
def _markdown_report_v2(audit: dict[str, Any]) -> str:  # noqa: E501
    families = audit["families"]
    findings = audit["findings"]  # noqa: E501
    priorities = Counter(item["priority"] for item in findings)
    signal_families: dict[str, set[str]] = {}
    for family_id, row in families.items():
        for item in row["quality_diagnostics"]["detected_signals"]:
            signal_families.setdefault(item["code"], set()).add(family_id)
    complete_five = sum(
        row["quality_diagnostics"]["sample_content_checks"]["examples_checked"] >= 5
        for row in families.values()
    )
    prior_review = sum(
        row["quality_diagnostics"]["example_review"]["prior_methodical_source_review_found"]
        for row in families.values()
    )
    lines = [
        "# Комплексный методический аудит банка ОГЭ №1–14",
        "",
        f"Обновлено: {audit['audit_date']} · база `20529867bc887bc6675c6cfc7a267fe0bf88d670`.",
        "",
        "## Охват и ограничения проверки",
        "",  # noqa: E501
        f"Runtime registry: **{audit['runtime_scope']['family_count']} активных семейств** "
        f"(40 сюжетных №1–5, 70 семейств №6–14); выключено/инвентаризировано "  # noqa: E501
        f"{len(audit['disabled_inventory'])} записей.",
        f"По всем {len(families)} семействам выполнена одна диагностическая процедура; "
        f"{complete_five} семейств имеют пять репрезентативных примеров с проверкой данных "
        "и независимым внутренним oracle. Каждый сюжет прогнан 600 раз; для подозрительных "
        "FLAT/GARDEN/PAPER вопросов отобрано до 300 примеров на family. Обычные family "
        "№6–14 получили не менее 50 seed; OGE07-C03/C04 — по 300.",
        f"Локальные источниковые материалы найдены для {prior_review} семейств "
        "(ссылки и статус у каждого family в JSON). Текущая проверка не открывала заново все "
        "внешние страницы; для семейств без явного prior review нельзя считать источник "
        "сверенным. Ручная оценка качества дистракторов, полноты подсказок и методической "
        "понятности отдельно обозначена как незавершённая.",
        "",
        "Успешный oracle подтверждает соответствие генерации собственной математической модели, "
        "но не соответствие официальному прототипу. Условия генераторов — аналоги, не копии.",
        "",
        "## Подтверждённые находки",  # noqa: E501
        "",
        "Автоматические сигналы не включены в приоритетный список, пока содержательная проверка "
        "не подтверждает проблему. PNG-таблица PAPER-F03 подписывает строку A0 и показывает "
        "ширину 841 мм, поэтому передача запрошенной величины подтверждена как P1. Старый "
        "отчёт не проверил именно графическую таблицу и смешал её с сырым snapshot.",
        "",
        f"Итого: P0 — {priorities['P0']}, P1 — {priorities['P1']}, "
        f"P2 — {priorities['P2']}, P3 — {priorities['P3']}.",
        "",
    ]
    if not findings:
        lines.extend(
            [
                "Подтверждённых дефектов по текущей процедуре нет; это не означает, что все ручные сверки завершены.",  # noqa: E501
                "",
            ]
        )
    for finding in findings:
        lines.extend(
            [
                f"### {finding['priority']} · {finding['family_id']} · {finding['id']}",
                "",
                f"**Seed:** `{finding.get('seed')}`. **Условие:** {finding.get('condition', '')}",
                f"**Ответ:** `{finding.get('answer', '')}`. **Почему:** {finding['explanation']}",
                f"**Исправление:** {finding['recommended_fix']}",
                f"**Source IDs:** {', '.join(map(str, finding.get('source_ids', []))) or 'нет'}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Сигналы, требующие ручной трактовки",
            "",
            "| Сигнал | Семейств | Family IDs |",
            "|---|---:|---|",
        ]
    )
    for code, ids in sorted(signal_families.items()):
        lines.append(
            f"| `{code}` | {len(ids)} | {', '.join(f'`{item}`' for item in sorted(ids))} |"
        )
    lines.extend(
        [
            "",
            "Сигналы являются поисковыми триггерами, а не выводами: узкий ответ может быть естественным "  # noqa: E501
            "для конечного прототипа; повтор конструкции не обязательно означает ошибку; лексическое "  # noqa: E501
            "несовпадение source metadata и условия может быть ложным сигналом.",
            "",
            "## Матрица 110 включённых семейств",
            "",
            "`preliminary` — прежняя экспертная гипотеза сложности из локальных атласов. "
            "`confirmed` оставлено пустым, пока отдельная экспертная калибровка на всём наборе "
            "примеров не проведена. Это не требование делать все задачи сложностью 3.",
            "",
            "| Family | № | Выборка | Полный сюжет | Условия вопроса | Значимые параметры | Ответы | Сложность: предварительная/подтверждённая | Сигналы | Source review |",  # noqa: E501
            "|---|---:|---:|---:|---:|---:|---:|---|---:|---|",
        ]
    )
    for family_id, row in sorted(families.items()):
        diag = row["quality_diagnostics"]
        diversity = diag["diversity"]
        complexity = row["method_complexity"]
        review = diag["example_review"]
        number = row.get("exam_number")
        lines.append(
            f"| `{family_id}` | {number} | {diag['sample_count']} | "
            f"{diversity['unique_full_story'] if diversity['unique_full_story'] is not None else '—'} | "  # noqa: E501
            f"{diversity['unique_question_conditions']} | {diversity['unique_significant_math_parameters']} | "  # noqa: E501
            f"{diversity['unique_answers']} | {complexity.get('preliminary_expert_hypothesis')}/— | "  # noqa: E501
            f"{len(diag['detected_signals'])} | "
            f"{'prior evidence' if review['prior_methodical_source_review_found'] else 'NOT VERIFIED'} |"  # noqa: E501
        )
    lines.extend(
        [
            "",
            "## Разнообразие сюжетов: сравнение с прежним 64-seed отчётом",
            "",
            "Прежний [OGE15_V2_DIVERSITY.md](OGE15_V2_DIVERSITY.md) считал вопросные сигнатуры с "
            "частью общей сцены и таблиц. Новые метрики отдельно показывают число полных сюжетов, "
            "тексты вопроса, значимые параметры его math model и ответы; изменения чужих вопросов "
            "не повышают разнообразие данного семейства. Объёмы выборок 64 и 50 различаются, "
            "поэтому сравнение направленное. Для FLAT-03, GARDEN-04, PAPER-F03/F04/F06 прежний "
            "отчёт давал 1 условие/1 сигнатуру/1 ответ; новый замер показывает до 300 полных "
            "сюжетов, но ровно 1 вопросное условие, 1 набор значимых параметров и 1 ответ. "
            "Другие вопросы меняли только full-story count, а не математическую задачу.",
            "",
            "## Методика и независимая проверка",
            "",
            "На каждом семействе анализируются одинаковые базовые поля: условие, ответ, параметры, "
            "подсказки, разбор, варианты, source IDs, стабильный fingerprint и результат oracle. "
            "Выборка пяти примеров включает крайние/центральные seed и seed автоматических сигналов. "  # noqa: E501
            "Проверяются пустые поля, дословный ответ в подсказке, дубли вариантов и oracle. "
            "Автоматический профиль distractor-distance и operation-vocabulary только создаёт signal.",  # noqa: E501
            "",
            "Источники представлены family-specific evidence из runtime registry/atlas и локальных "
            "quality reports. Полная повторная веб-сверка источников для №6–14 и независимая "
            "проверка всех графиков №11 не завершены; этим семействам в JSON назначен статус "
            "`manual_review_incomplete`, а не `passed`.",
            "",
            "Сложность не объявляется подтверждённой автоматически: сохранившиеся баллы — "
            "предварительные экспертные гипотезы; поле подтверждённого балла — `null` до общей "
            "экспертной калибровки.",
            "",
            "## Scheduler и изображения",
            "",
            "Последовательности scheduler по 20 заданий для №6–14 и 20 связанных комплектов №1–5 "
            "сохранены в JSON. Сюжетные PNG-превью имеют ширину 390 px и повторяют порядок показа: "
            "текст контекста, фотографии/таблицы, затем вопрос. Это локальные превью, не скриншоты Telegram.",  # noqa: E501
            "",
            "## Выключенные семейства и ограничения",
            "",
            f"Все {len(audit['disabled_inventory'])} выключенных/исследовательских записей описаны в JSON. "  # noqa: E501
            "Для них массовая генерация не выполнялась. ROUTE остаётся выключен.",
            "",
            "## Воспроизведение",
            "",
            "```bash",
            "uv run python scripts/oge_bank_quality_audit.py",
            "# optional: full raw sample outside Git",
            "uv run python scripts/oge_bank_quality_audit.py --full-output /tmp/oge-bank-full.json",
            "```",
            "",
            "Компактный JSON содержит для каждого семейства сигналы, 5 воспроизводимых примеров, "
            "source status и метрики. Полная сырая выборка хранится только по запросу запуска.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    from app.bot.trainings import TRAININGS

    raw_samples: dict[str, list[dict[str, Any]]] = {}
    scenario_result, best_scenario_plans = _scenario_audit()
    reference_rows = _registry_reference_rows()
    families: dict[str, Any] = {}
    preview_objects: dict[int, dict[str, list[Any]]] = {number: {} for number in range(6, 15)}
    for story_family, rows in scenario_result["families"].items():
        story = next(code for code, ids in PUBLIC_FAMILIES.items() if story_family in ids)
        registration = next(
            item
            for item in public_registry().adapter(story).family_registry
            if item.family_id == story_family
        )
        families[story_family] = _summarize(1, story_family, rows, [])
        families[story_family].update(
            {
                "exam_number": "1-5",
                "story": story,
                "position": registration.position,
                "runtime_status": registration.status.value,
                "enabled_for_students": registration.available,
                "source_ids": list(registration.source_ids),
                "source_evidence": {
                    "review": "reports/OGE15_V2_FAMILY_REVIEW.md",
                    "acceptance": "reports/OGE15_V2_SOURCE_ACCEPTANCE.md",
                    "coverage": (
                        "specs/coverage/OGE15_PAPER_COVERAGE.md"
                        if story == "PAPER"
                        else f"reports/oge15-{story.lower()}-coverage.md"
                    ),
                    "source_ids": list(registration.source_ids),
                    "provenance_note": (
                        "Сверка относится к выбранным каталожным карточкам и подтверждённым "
                        "структурам из acceptance report; generated analogues не являются "
                        "копиями официальных задач."
                    ),
                },
                "method_complexity": {
                    "score": SCENARIO_COMPLEXITY.get(story_family, 3),
                    "rationale": (
                        "Экспертная оценка семейства "
                        f"«{_atlas_evidence(story_family).get('name', story_family)}»: "
                        "учтены требуемое действие, число шагов, чтение общей схемы/таблицы "
                        "и зависимость от общего сюжета; пять seed и ответы приведены в JSON."
                    ),
                    "reviewed_example_seed": rows[0].get("seed") if rows else None,
                },
                "source_basis": (
                    "Источники и статус описаны в source_evidence; все новые условия "
                    "помечаются как generated analogue."
                ),
                "sample_requirement": SAMPLE_SEEDS,
                "actual_sample_count": len(rows),
                "generator_version": rows[0].get("generator_version") if rows else None,
            }
        )
    for training in TRAININGS:  # noqa: E501
        number = training.number
        if not training.available:
            continue
        generator = importlib.import_module(
            {
                6: "app.math.generator",
                7: "app.math.oge07_scheduler",
                8: "app.math.oge8",
                9: "app.math.equations",
                10: "app.math.probability",
                11: "app.math.oge11",
                12: "app.math.formulas",
                13: "app.math.inequalities",
                14: "app.math.progressions",
            }[number]
        )
        enabled = (
            tuple(
                spec.family_id
                for spec in importlib.import_module("app.math.registry").GENERATOR_SPECS
            )
            if number == 6
            else tuple(generator.ENABLED_FAMILIES)
        )
        for family in enabled:
            size = EXTENDED_SEEDS.get(family, SAMPLE_SEEDS)
            print(f"OGE {number} {family}: {size} deterministic samples", flush=True)
            summary, raw_examples = _family_audit(number, family, size)
            metadata = {}
            if raw_examples:
                first = raw_examples[0]
                metadata = {
                    "source_ids": list(getattr(first, "reference_ids", ())),
                    "generator_version": str(getattr(first, "generator_version", "")),
                    "answer_policy_id": str(
                        getattr(
                            first,
                            "answer_policy_id",
                            getattr(getattr(first, "answer_policy", None), "policy_id", ""),
                        )
                    ),
                    "answer_policy_version": str(
                        getattr(
                            first,
                            "answer_policy_version",
                            getattr(getattr(first, "answer_policy", None), "version", ""),
                        )
                    ),
                }
            if not metadata.get("source_ids"):
                metadata["source_ids"] = _reference_source_ids(reference_rows.get(family, {}))
            families[family] = {
                "exam_number": number,
                "runtime_status": "enabled",
                "enabled_for_students": True,
                "sample_requirement": size,
                **summary,
                **metadata,
                "source_evidence": reference_rows.get(family) or _atlas_evidence(family),
            }
            preview_objects[number][family] = raw_examples
    for family_id, family_row in families.items():
        raw_samples[family_id] = family_row.get("samples", [])
        diagnostics = _diagnose_family(family_id, family_row)
        selected = _representative_samples(family_row, diagnostics["detected_signals"])
        diagnostics["sample_content_checks"] = _sample_content_checks(selected)
        for signal in diagnostics["detected_signals"]:
            signal["examples"] = [_compact_sample(sample) for sample in signal["examples"]]
        evidence = family_row.get("source_evidence", {})
        evidence_text = _stable(evidence)
        prior_review = (
            family_row.get("exam_number") == "1-5"
            and (ROOT / "reports/OGE15_V2_FAMILY_REVIEW.md").exists()
        ) or bool(
            re.search(
                r"individually checked|source text|structure.*checked|verified", evidence_text, re.I
            )
        )
        diagnostics["example_review"].update(
            {
                "prior_methodical_source_review_found": prior_review,
                "current_run_source_text_rechecked": False,
                "current_run_manual_distractor_review": False,
            }
        )
        family_row["quality_diagnostics"] = diagnostics
        complexity = family_row.get("method_complexity", {})
        family_row["method_complexity"] = {
            "preliminary_expert_hypothesis": complexity.get("score"),
            "confirmed_score": None,
            "status": "not confirmed by this automated run",
            "preliminary_rationale": complexity.get("rationale"),
        }
        family_row["representative_examples"] = [_compact_sample(sample) for sample in selected]
        family_row["quality_diagnostics"]["example_review"]["seeds"] = [
            sample.get("seed") for sample in selected
        ]
        family_row.pop("samples", None)
    scenarios = scenario_result["stories"]
    audit = {
        "schema_version": 2,
        "audit_date": "2026-11-13",
        "base_commit": "2052986",
        "seed_namespace": SEED_NAMESPACE,
        "sampling": {
            "enabled_non_scenario_families": SAMPLE_SEEDS,
            "extended_families": EXTENDED_SEEDS,
            "full_scenario_bundles_per_story": SCENARIO_SEEDS,
            "scenario_examples_per_family_target": SAMPLE_SEEDS,
            "scheduler_sequence_per_number": 20,
            "source_note": "Source IDs, prior evidence and fresh verification status are separate fields; source URLs/text are not fetched in this run.",  # noqa: E501
        },
        "runtime_scope": {
            "scenario_public_families": sum(len(v) for v in PUBLIC_FAMILIES.values()),
            "scenario_public_stories": sorted(PUBLIC_FAMILIES),
            "available_numbered_families": sum(
                1
                for item in families.values()
                if isinstance(item.get("exam_number"), int) and item["exam_number"] >= 6
            ),
            "family_count": len(families),
            "numbers_available": [t.number for t in TRAININGS if t.available],
        },
        "scenario_bundles": scenarios,
        "families": families,
        "disabled_inventory": _disabled_inventory(),
        "sequence_sampling": _sequence_audit(),
        "prior_quality_reports": _quality_references(),
        "findings": [],
    }
    audit["findings"] = _confirmed_findings(families)
    preview_paths = _scenario_previews(best_scenario_plans)
    for number in range(6, 15):
        preview_paths.extend(_number_previews(number, preview_objects))
    audit["mobile_previews"] = {
        "width_px": MOBILE_WIDTH,
        "assets": preview_paths,
        "note": (
            "Local PNG renders resized to 390 px wide; visual inspection is incomplete, "
            "and these are not Telegram-client screenshots."
        ),
    }
    REPORT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_REPORT.write_text(_markdown_report_v2(audit), encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-output",
        type=Path,
        help="optional path for the unabridged fixed-seed sample (not committed by default)",
    )
    args = parser.parse_args()
    if args.full_output:
        args.full_output.parent.mkdir(parents=True, exist_ok=True)
        args.full_output.write_text(
            json.dumps(
                {
                    "base_commit": audit["base_commit"],
                    "seed_namespace": SEED_NAMESPACE,
                    "families": raw_samples,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote full sample {args.full_output}", flush=True)
    print(f"Wrote {REPORT}", flush=True)
    print(f"Wrote {MARKDOWN_REPORT}", flush=True)
    return audit


if __name__ == "__main__":
    run()
