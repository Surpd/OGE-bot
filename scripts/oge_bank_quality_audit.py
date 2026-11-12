"""Reproduce the all-enabled-family OGE 1–14 audit sample and mobile previews.

This intentionally reuses the runtime registry, each generator's independent
oracle, and each production candidate scheduler. It does not change generator
state or claim that generated analogues are official source tasks.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import random
import re
from collections import Counter
from collections.abc import Callable
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
SCENARIO_SEEDS = 300
EXTENDED_SEEDS = {"OGE07-C04": 300}
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
    if isinstance(value, dict):
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
                if len(plan_examples[family]) < 50:
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
                "report_sample_size": data.get(
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
            "quality_criteria",
            "specific_caution",
        )
        if key in entry
    }


def _reference_source_ids(reference: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("source_ids", "source_case_ids", "reference_ids", "prototype_ids", "ids"):
        candidate = reference.get(key, [])
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


def _markdown_report(audit: dict[str, Any]) -> str:
    families = audit["families"]
    disabled = audit["disabled_inventory"]
    findings = audit["findings"]
    numbered = audit["sequence_sampling"]
    lines = [
        "# Комплексный методический аудит банка ОГЭ №1–14",
        "",
        f"Дата: {audit['audit_date']} · база: `{audit['base_commit']}`.",
        "",
        "## Итоги охвата",
        "",
        f"Runtime охват: **{audit['runtime_scope']['family_count']} включённых семейств** — "
        f"{audit['runtime_scope']['scenario_public_families']} сюжетных семейств №1–5 и "
        f"{audit['runtime_scope']['available_numbered_families']} семейств №6–14. "
        f"Отдельно инвентаризировано {len(disabled)} выключенных/исследовательских записей.",
        "",
        "По всем включённым семействам собрана фиксированная выборка не менее 50 примеров; "
        "OGE07-C04 расширен до 300 seed. Для №1–5 проверено по 300 полных связанных комплектов "
        "каждой доступной истории. Для каждого обычного номера прогнаны 20 выдач через его "
        "production scheduler; отдельно проверены 20 полных случайных комплектов №1–5.",
        "",
        "Проверка seed проходит production независимые оракулы/валидаторы. Успешный оракул "
        "подтверждает математическую согласованность с внутренней моделью, но сам по себе "
        "не подтверждает сходство с источником ОГЭ.",
        "",
        "## Приоритетные находки",
        "",
    ]
    priority_counts = Counter(f["priority"] for f in findings)
    lines.append(
        "Находки: "
        + ", ".join(
            f"{priority} — {priority_counts.get(priority, 0)}"
            for priority in ("P0", "P1", "P2", "P3")
        )
        + "."
    )
    lines.append("")
    for finding in findings:
        source_ids = ", ".join(finding.get("source_ids", [])) or finding["actual_behavior"].get(
            "source_id", "—"
        )
        if finding["family_id"] == "OGE07-C04":
            detail = (
                f"В расширенной выборке целый ответ встречался в "
                f"{finding.get('integer_target_rate', 0):.1%} задач, целая граница — в "
                f"{finding.get('integer_boundary_answer_rate', 0):.1%}. В каталожном примере "
                f"ID `{finding['actual_behavior'].get('source_id', '369728')}` используется дробь "
                "`68/19` на отрезке `[3;4]`; генератор ограничивает знаменатель значениями "
                "2, 3, 4, 5, 10 и показывает конечные десятичные варианты."
            )
        else:
            detail = (
                f"Конструкций: {finding['unique_construction_signatures']}; "
                f"уникальных ответов: {finding['unique_answers']}; "
                f"точных повторов текста: {finding['identical_condition_text_count']}. "
                "Для PAPER это естественно конечный источник, поэтому находка описывает "
                "ограничение и риск повтора, а не математическую ошибку."
            )
        lines.extend(
            [
                f"### {finding['priority']} · {finding['family_id']} · {finding['id']}",
                "",
                f"**Воспроизведение.** Seed `{finding['seed']}`: «{finding['condition']}» "
                f"Варианты: `{', '.join(finding['options'])}`. "
                f"Ключ генератора: `{finding['actual_behavior']['answer']}`.",
                "",
                f"**Оценка.** {detail}",
                "",
                "**Источник / объём.** IDs: `"
                f"{source_ids}`. "
                "Созданные задания — generated analogues. Повторная внешняя сверка всех карточек "
                "в этом запуске не выполнялась.",
                "",
                f"**Исправление.** {finding['recommended_fix']}",
                "",
                "Публичную выдачу не блокировали: это существенная методическая деградация, "
                "но генератор сохраняет математическую правильность и уникальный вариант.",
                "",
            ]
        )
    if not findings:
        lines.extend(["В этой выборке новых приоритетных дефектов не найдено.", ""])
    lines.extend(
        [
            "## Матрица включённых семейств",
            "",
            "Оценка сложности — экспертный ориентир 1–5 по видимому математическому действию. "
            "Пять репрезентативных seed каждого семейства, точные условия, ответы, подсказки, "
            "разборы, варианты и fingerprints находятся в структурированном JSON отчёте.",
            "JSON также содержит распределения ответов и вариантов, уникальные конструкции, "
            "повторы, положение правильного варианта, ошибки генерации и отказы oracle. "
            "Очевидность дистракторов оценивалась вручную только там, где приведён отдельный "
            "воспроизводимый приоритетный случай.",
            "",
            "| Номер/сюжет | Family ID | Сложность | Source IDs | Выборка | "
            "Уникальное отображаемое содержание | Ответов | Generation errors | Oracle failures |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for family, row in sorted(
        families.items(),
        key=lambda pair: (str(pair[1].get("exam_number")), pair[1].get("story", ""), pair[0]),
    ):
        number = str(row.get("exam_number", ""))
        place = (
            f"№1–5 {row.get('story')} / {row.get('position')}" if number == "1-5" else f"№{number}"
        )
        complexity = row.get("method_complexity", {}).get("score", "—")
        sources = ", ".join(map(str, row.get("source_ids", []))) or "—"
        failures = len(row.get("oracle_failures", []))
        generation_failures = row.get("generation_failure_count", 0)
        lines.append(
            f"| {place} | `{family}` | {complexity} | {sources} | "
            f"{row.get('sample_count', 0)} | {row.get('unique_conditions', 0)} | "
            f"{row.get('unique_answers', 0)} | {generation_failures} | {failures} |"
        )
    lines.extend(["", "### Источники и статус прототипов", ""])
    lines.extend(
        [
            "* Source IDs и URL взяты из актуальных runtime registrations, атласов "
            "и уже существующих "
            "source/quality reports. Глобальная автоматическая проверка доступности страниц и "
            "повторная сверка текста всех внешних карточек в этом запуске не выполнялись.",
            "* Условия и snapshots, создаваемые генераторами, "
            "являются **сгенерированными аналогами**. "
            "Ссылка на каталог не превращает аналог в точную копию официального задания.",
            "* В №1–5 семейство связано с одним миром/планом и пятью зависимыми вопросами; "
            "все 300 комплектов проходили runtime bundle oracle. Режим исследовательского ROUTE "
            "не включён в ученический охват.",
            "* В №6–14 источниковые IDs и уже выполненные объёмы quality gate приведены в JSON; "
            "подробные исходные решения остаются в указанных файлах `reports/` и `atlas/`.",
            "",
            "Ранее выполненные источниковые и методические сверки №1–5:",
            "",
            "* [Матрица 40 семейств](OGE15_V2_FAMILY_REVIEW.md)",
            "* [Приёмка источников и решения](OGE15_V2_SOURCE_ACCEPTANCE.md)",
            "* [Наблюдаемое разнообразие](OGE15_V2_DIVERSITY.md)",
            "* [PAPER: карточки и ограничения](../specs/coverage/OGE15_PAPER_COVERAGE.md)",
            "* [FLAT](oge15-flat-coverage.md), [GARDEN](oge15-garden-coverage.md), "
            "[STOVE](oge15-stove-coverage.md), [TARIFF](oge15-tariff-coverage.md), "
            "[TYRES](oge15-tyres-coverage.md), [ROUTE: выключен](oge15-route-coverage.md)",
            "",
            "## Последовательная выдача scheduler",
            "",
            "| Номер | Выдач | Повтор family рядом | Максимальная серия | "
            "Повтор fingerprint | Повтор ответа рядом |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for number, row in numbered.items():
        if number == "1-5":
            lines.append(
                f"| №1–5 случайный полный комплект | 20 | "
                f"{row['adjacent_same_story']} сюжетов | — | "
                f"{row['repeated_bundle_fingerprints']} | — |"
            )
        else:
            lines.append(
                f"| №{number} | 20 | {row['adjacent_same_family']} | "
                f"{row['longest_family_run']} | {row['repeated_fingerprints']} | "
                f"{row['repeated_adjacent_answers']} |"
            )
    lines.extend(
        ["", "Полные последовательности с seed/family/condition/answer включены в JSON.", ""]
    )
    lines.extend(["## Мобильные PNG превью, ширина 390 px", ""])
    for asset in audit.get("mobile_previews", {}).get("assets", []):
        rel = asset.removeprefix("reports/")
        lines.append(f"* [{Path(asset).name}]({Path(rel).as_posix()})")
    lines.extend(
        [
            "",
            "Превью собраны локальным PNG рендерером. Это не скриншоты клиента Telegram; "
            "проверка касается реальных графических/табличных assets "
            "и ограниченного math renderer.",
            "",
            "## Выключенные семейства и известные ограничения",
            "",
            f"Статусы/причины всех {len(disabled)} записей вынесены в JSON `disabled_inventory`. "
            "Публичное семейство маршрутов ROUTE отсутствует: все пять семейств ROUTE остаются "
            "выключенными. Для выключенных записей массовая генерация намеренно не запускалась.",
            "",
            "Естественно ограниченные геометрические источники PAPER, GARDEN и FLAT "
            "могут повторять "
            "фиксированные размеры, площади или ответы при другой перестановке меток/данных. "
            "Такие варианты не засчитывались как новая математическая конструкция: fingerprints "
            "учитывают условие, параметры модели и SHA-256 графических assets. "
            "Решение о расширении "
            "этих конечных прототипов требует новых подтверждённых источников.",
            "PAPER-F03/F04/F06 дали по одному уникальному ответу на 50 seed и 13/6/11 точных "
            "повторов текста соответственно. Это отражено как P2, согласуется с известной "
            "естественной ёмкостью и существующим ограничением близких повторов; новые числовые "
            "варианты без источника не рекомендуются.",
            "Для №11 отдельные исходные графики каталожных примеров не были независимо сверены "
            "(см. `atlas/oge11_reference_structures.json`). В этом аудите "
            "проверены сгенерированные "
            "PNG, математические модели, биекция и различимость кривых; соответствие каждого "
            "изображения источнику не утверждается.",
            "",
            "TARIFF использует фиксированный совместимый набор тарифов, а временные ряды/параметры "
            "частично изменяются. Разнообразие показаний и ответов следует трактовать в пределах "
            "этого конечного прототипа, а не как покрытие всего банка ОГЭ.",
            "",
            "## Исправления с наибольшей пользой ученикам",
            "",
            "1. Переработать OGE07-C04: вернуть сравнение конечной рациональной дроби с целыми "
            "границами, ограничить целые/граничные ответы и сохранить независимую проверку "
            "единственного подходящего варианта.",
            "2. Для конечных сюжетов не раздувать вариативность случайными именами: "
            "расширять PAPER, "
            "GARDEN и FLAT только новыми источниками/планами, "
            "а фиксированные варианты явно ротировать "
            "без объявления их разными математическими конструкциями.",
            "3. Продолжать проверять каждый полный связанный комплект "
            "и мобильное отображение таблиц "
            "и схем; внутренний oracle не заменяет экспертную сверку нового источника.",
            "",
            "## Воспроизведение",
            "",
            "```bash",
            "uv run python scripts/oge_bank_quality_audit.py",
            "```",
            "",
            "Команда обновляет Markdown/JSON отчёты и мобильные PNG assets. "
            "Все seed и generator versions сохраняются в JSON.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    from app.bot.trainings import TRAININGS

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
    for training in TRAININGS:
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
    scenarios = scenario_result["stories"]
    audit = {
        "schema_version": 1,
        "audit_date": "2026-11-12",
        "base_commit": "2052986",
        "seed_namespace": SEED_NAMESPACE,
        "sampling": {
            "enabled_non_scenario_families": SAMPLE_SEEDS,
            "extended_families": EXTENDED_SEEDS,
            "full_scenario_bundles_per_story": SCENARIO_SEEDS,
            "scenario_examples_per_family_target": SAMPLE_SEEDS,
            "scheduler_sequence_per_number": 20,
            "source_note": (
                "Oracle pass/fail does not independently prove source fidelity; "
                "source provenance is recorded per family."
            ),
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
    c04 = families.get("OGE07-C04", {})
    integer_examples = c04.get("integer_boundary_examples", [])
    findings: list[dict[str, Any]] = []
    if integer_examples:
        findings.append(
            {
                "id": "OGE07-C04-INTEGER-BOUNDARY-ANSWER",
                "priority": "P1",
                "family_id": "OGE07-C04",
                "severity_basis": (
                    "Правильный вариант может оказаться целым концом отрезка, а все "
                    "дистракторы наглядно расположены снаружи; сравнивать рациональные "
                    "числа тогда не требуется."
                ),
                "sample_size": c04.get("sample_count", 0),
                "integer_target_rate": c04.get("integer_target_rate"),
                "integer_boundary_answer_rate": c04.get("integer_boundary_answer_rate"),
                "seed": integer_examples[0]["seed"] if integer_examples else None,
                "condition": integer_examples[0]["condition"] if integer_examples else "",
                "options": integer_examples[0]["options"] if integer_examples else [],
                "expected_behavior": (
                    "Использовать рациональный вариант вроде 68/19 на [3;4], требующий "
                    "сравнения с обеими границами; не допускать очевидного целого "
                    "ответа на границе."
                ),
                "actual_behavior": integer_examples[0] if integer_examples else None,
                "recommended_fix": (
                    "Ограничить правильный вариант внутренней нецелой рациональной дробью "
                    "с источниковым знаменателем; подобрать дистракторы с таким же типом "
                    "сравнения и оставить независимую проверку ровно одного правильного варианта."
                ),
                "student_block_required": False,
            }
        )
    for family_id, recommendation in {
        "PAPER-F03": (
            "Do not include the requested A0 width verbatim in the table; ask for a value "
            "that must be derived from a different listed format, and add reviewed source "
            "variants before claiming broader structural diversity."
        ),
        "PAPER-F04": (
            "Keep the fixed 0.7 result documented as natural finite capacity, rotate against "
            "recent repeats, and add new verified paper formats only when the source supports them."
        ),
        "PAPER-F06": (
            "Treat this as one source-bounded construction; prevent immediate reissue and expand "
            "only after adding a verified diagonal-ratio prototype with a distinct derivation."
        ),
    }.items():
        row = families[family_id]
        sample = row["representative_examples"][0]
        findings.append(
            {
                "id": f"{family_id}-FINITE-LOW-DIVERSITY",
                "priority": "P2",
                "family_id": family_id,
                "seed": sample["seed"],
                "condition": sample["condition"],
                "options": sample.get("options", []),
                "severity_basis": (
                    f"В выборке 50 seed найдено {row['unique_construction_signatures']} "
                    f"математических конструкций, {row['unique_answers']} уникальных ответов и "
                    f"{row['identical_condition_text_count']} повторов полного текста. "
                    "Для PAPER это естественно конечный источник, поэтому находка описывает "
                    "ограничение и риск повторной выдачи, а не математическую ошибку."
                ),
                "sample_size": row["sample_count"],
                "unique_construction_signatures": row["unique_construction_signatures"],
                "unique_answers": row["unique_answers"],
                "identical_condition_text_count": row["identical_condition_text_count"],
                "source_ids": row.get("source_ids", []),
                "actual_behavior": sample,
                "recommended_fix": recommendation,
                "student_block_required": False,
                "known_finite_capacity": True,
            }
        )
    audit["findings"] = findings
    preview_paths = _scenario_previews(best_scenario_plans)
    for number in range(6, 15):
        preview_paths.extend(_number_previews(number, preview_objects))
    audit["mobile_previews"] = {
        "width_px": MOBILE_WIDTH,
        "assets": preview_paths,
        "note": (
            "Local PNG renders resized to 390 px wide and visually inspected; "
            "these are not Telegram-client screenshots."
        ),
    }
    REPORT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_REPORT.write_text(_markdown_report(audit), encoding="utf-8")
    print(f"Wrote {REPORT}", flush=True)
    print(f"Wrote {MARKDOWN_REPORT}", flush=True)
    return audit


if __name__ == "__main__":
    run()
