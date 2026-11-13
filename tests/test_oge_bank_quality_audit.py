from __future__ import annotations

from app.bot.scenario_training import PUBLIC_FAMILIES
from app.bot.trainings import TRAININGS
from scripts.oge_bank_quality_audit import (
    COMPLEXITY,
    SCENARIO_COMPLEXITY,
    _confirmed_findings,
    _diagnose_family,
    _disabled_inventory,
    _diversity_keys,
    _ordinary_generator,
    _representative_samples,
    _seed_sequence,
)


def test_fixed_seed_samples_are_reproducible_and_c04_keeps_regression_seed() -> None:
    assert _seed_sequence(7, "OGE07-C04", 300) == _seed_sequence(7, "OGE07-C04", 300)
    assert _seed_sequence(7, "OGE07-C04", 300)[0] == 6
    assert len(set(_seed_sequence(7, "OGE07-C04", 300))) == 300


def test_complexity_rubric_covers_every_runtime_enabled_family() -> None:
    scenario_families = {family for values in PUBLIC_FAMILIES.values() for family in values}
    assert scenario_families == set(SCENARIO_COMPLEXITY)
    assert all(1 <= score <= 5 for score in SCENARIO_COMPLEXITY.values())
    for training in TRAININGS:
        if training.available and training.number >= 6:
            runtime_families, _ = _ordinary_generator(training.number)
            assert set(runtime_families) == set(COMPLEXITY[training.number])
            assert all(1 <= score <= 5 for score in COMPLEXITY[training.number].values())


def test_disabled_inventory_has_a_reason_or_explicit_reference_gap() -> None:
    rows = _disabled_inventory()
    assert rows
    assert all(row["family_id"] and row["runtime_status"] for row in rows)
    assert all(row.get("reason") for row in rows)


def test_story_context_variation_does_not_count_as_question_diversity() -> None:
    first = {
        "question_text": "Найдите площадь лоджии.",
        "condition": "Сюжет A. Найдите площадь лоджии.",
        "full_story_fingerprint": "story-a",
        "construction_parameters": {"cells": 30, "cell_area": "0.16"},
        "answer": "4,8",
    }
    second = {
        **first,
        "condition": "Сюжет B. Найдите площадь лоджии.",
        "full_story_fingerprint": "story-b",
    }
    first_keys = _diversity_keys(first, scenario=True)
    second_keys = _diversity_keys(second, scenario=True)
    assert first_keys["full_story"] != second_keys["full_story"]
    assert first_keys["question_condition"] == second_keys["question_condition"]
    assert first_keys["significant_parameters"] == second_keys["significant_parameters"]


def test_obvious_interval_distractors_are_a_signal_not_an_automatic_finding() -> None:
    samples = [
        {
            "seed": 6,
            "condition": "Какое число принадлежит отрезку [0; 2]?",
            "question_text": "Какое число принадлежит отрезку [0; 2]?",
            "answer": "0",
            "options": ["3", "3,5", "−1", "0"],
            "valid_oracle": True,
            "hints": ["Сравните с концами"],
            "solution": ["Ответ 0"],
        }
    ]
    row = {"exam_number": 7, "samples": samples, "source_evidence": {}}
    diagnostics = _diagnose_family("synthetic-family", row)
    codes = {item["code"] for item in diagnostics["detected_signals"]}
    assert "correct_interval_endpoint_with_external_distractors" in codes
    assert diagnostics["confirmed_findings"] == []
    assert diagnostics["diagnostic_status"] == "sampled; manual review incomplete"


def test_perfect_square_radical_endpoint_is_discovered_from_sampled_content() -> None:
    sample = {
        "seed": 981,
        "condition": "Какой радикал принадлежит отрезку [7; 9]?",
        "question_text": "Какой радикал принадлежит отрезку [7; 9]?",
        "answer": "√81",
        "options": ["√81", "√12", "√22", "√14"],
        "valid_oracle": True,
        "hints": ["Сравните квадраты"],
        "solution": ["√81 = 9"],
    }
    diagnostics = _diagnose_family("unlisted-family", {"exam_number": 7, "samples": [sample]})
    codes = {item["code"] for item in diagnostics["detected_signals"]}
    assert "perfect_square_radical_at_interval_endpoint" in codes
    assert diagnostics["confirmed_findings"] == []


def test_serialized_story_context_is_not_used_as_visible_leak_without_display_evidence() -> None:
    sample = {
        "seed": 203,
        "condition": "A0: 1189 × 841 мм. Найдите ширину A0.",
        "question_text": "Найдите ширину A0.",
        "displayed_shared_context": "Таблица без названий форматов: 420×297; 1189×841.",
        "answer": "840",
        "construction_parameters": {"width_mm": 841, "round_to": 10},
        "valid_oracle": True,
        "hints": ["Сначала определите формат по общему правилу"],
        "solution": ["841 мм округляется до 840 мм"],
    }
    diagnostics = _diagnose_family("PAPER-F03", {"exam_number": "1-5", "samples": [sample]})
    codes = {item["code"] for item in diagnostics["detected_signals"]}
    assert "requested_value_appears_in_serialized_context" not in codes


def test_labeled_visible_table_target_measurement_is_detected() -> None:
    sample = {
        "seed": 21771112,
        "condition": "Таблица A0: 1189 × 841 мм. Найдите ширину A0 и округлите.",
        "question_text": "Найдите ширину листа формата A0 и округлите.",
        "displayed_shared_context": "Общий текст; см. таблицу",
        "scenario_context": {"rows": [["A0", 1189, 841], ["A3", 420, 297]]},
        "answer": "840",
        "construction_parameters": {"format_index": 0, "side": "short", "value_mm": 841},
        "valid_oracle": True,
        "hints": ["Округлите до ближайшего десятка"],
        "solution": ["841 округляется до 840"],
    }
    diagnostics = _diagnose_family("PAPER-F03", {"exam_number": "1-5", "samples": [sample]})
    codes = {item["code"] for item in diagnostics["detected_signals"]}
    assert "requested_measurement_disclosed_in_labeled_shared_table" in codes


def test_labeled_table_does_not_trigger_disclosure_for_count_or_ratio_questions() -> None:
    samples = [
        {
            "seed": 219,
            "question_text": question,
            "scenario_context": {"rows": [["A6", 148, 105], ["A3", 420, 297]]},
            "answer": answer,
            "construction_parameters": {"operation": operation},
            "valid_oracle": True,
        }
        for question, answer, operation in (
            ("Сколько листов формата A6 получится из одного листа A4?", "8", "count"),
            ("Найдите отношение меньшей стороны листа формата A3 к большей.", "0,7", "ratio"),
        )
    ]
    diagnostics = _diagnose_family("PAPER-F02", {"exam_number": "1-5", "samples": samples})
    codes = {item["code"] for item in diagnostics["detected_signals"]}
    assert "requested_measurement_disclosed_in_labeled_shared_table" not in codes


def test_collapsed_question_finding_is_derived_from_measurement_not_family_ids() -> None:
    samples = [
        {
            "seed": index,
            "question_text": "Найдите площадь прямоугольника.",
            "condition": "Сюжет меняется, вопрос тот же.",
            "full_story_fingerprint": f"story-{index}",
            "answer": "12",
            "construction_parameters": {"area": 12},
            "valid_oracle": True,
        }
        for index in range(50)
    ]
    diagnostics = _diagnose_family(
        "family-never-listed-in-code", {"exam_number": "1-5", "samples": samples}
    )
    signal = next(
        item
        for item in diagnostics["detected_signals"]
        if item["code"] == "question_construction_collapsed_to_one_observed_case"
    )
    assert signal["signal_count"] == 50
    assert diagnostics["diversity"]["unique_full_story"] == 50
    assert diagnostics["diversity"]["unique_question_conditions"] == 1
    assert diagnostics["diversity"]["unique_answers"] == 1
    finding = _confirmed_findings(
        {
            "family-never-listed-in-code": {
                "sample_count": 50,
                "quality_diagnostics": diagnostics,
                "representative_examples": samples[:5],
            }
        }
    )[0]
    assert finding["priority"] == "P2"
    assert finding["family_id"] == "family-never-listed-in-code"


def test_sample_review_selects_reproducible_extremes_and_suspicious_example() -> None:
    samples = [{"seed": index, "answer": str(index), "valid_oracle": True} for index in range(10)]
    selected = _representative_samples({"samples": samples}, [{"code": "trigger", "seeds": [7]}])
    assert len(selected) == 5
    assert samples[7] in selected
    assert samples[0] in selected
    assert samples[-1] in selected
