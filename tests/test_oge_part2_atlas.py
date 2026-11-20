from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path, PurePosixPath

from PIL import Image

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "part2"


def _cards() -> list[dict]:
    with (ATLAS / "tasks.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def test_static_bank_matches_taxonomy_and_coverage() -> None:
    cards = _cards()
    taxonomy = json.loads((ATLAS / "taxonomy.json").read_text(encoding="utf-8"))
    subtypes = {subtype["subtype_id"]: subtype for subtype in taxonomy["subtypes"]}
    with (ATLAS / "coverage_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
        coverage = {row["subtype_id"]: row for row in csv.DictReader(handle)}

    counts = Counter(card["subtype_id"] for card in cards)
    sources = Counter(card["subtype_id"] for card in cards if card["bank_scope"] == "source_based")
    assert counts.keys() == subtypes.keys() == coverage.keys()
    assert len({card["task_id"] for card in cards}) == taxonomy["curated_task_count"] == len(cards)
    assert {card["number"] for card in cards} == set(range(20, 26))
    assert sum(sources.values()) == taxonomy["source_card_count"]
    assert len(cards) - sum(sources.values()) == taxonomy["authored_training_card_count"]

    for subtype_id, count in counts.items():
        assert taxonomy["target_count_per_subtype"] <= count <= 10
        assert subtypes[subtype_id]["complete_cards"] == count
        assert int(coverage[subtype_id]["total"]) == count
        assert int(coverage[subtype_id]["source_based"]) == sources[subtype_id]
        assert int(coverage[subtype_id]["atlas_original"]) == count - sources[subtype_id]

    for card in cards:
        subtype = subtypes[card["subtype_id"]]
        assert card["family_id"] == subtype["family_id"]
        assert card["number"] == subtype["number"]
        assert card["task_id"] in subtype["card_ids"]


def test_cards_keep_hints_solutions_and_source_provenance() -> None:
    for card in _cards():
        assert card["statement"].strip()
        assert card["answer_or_claim"].strip()
        assert card["reference_solution"].strip()
        assert len(card["hints"]) == 2 and all(hint.strip() for hint in card["hints"])
        assert len(card["solution_steps"]) >= 2
        assert all(step.strip() for step in card["solution_steps"])
        assert card["rubric"]["maximum"] == 2
        assert set(card["rubric"]["levels"]) == {"0", "1", "2"}
        assert card["bank_scope"] in {"source_based", "training_only"}
        if card["bank_scope"] == "training_only":
            assert card["source_kind"] == "atlas_original"
            assert card["source_url"] is None
            assert card["model_reference"].startswith("https://")
        else:
            assert card["source_kind"] != "atlas_original"
            assert card["source_url"].startswith("https://")


def test_graphs_and_diagrams_reference_valid_png_files() -> None:
    figures = set()
    for card in _cards():
        visuals = card["visuals"]
        kinds = {visual["kind"] for visual in visuals}
        if card["number"] == 22:
            assert "graph" in kinds
        elif card["number"] >= 23:
            assert "geometry_diagram" in kinds

        for visual in visuals:
            path = PurePosixPath(visual["path"])
            assert path.parts == ("figures", path.name) and path.suffix == ".png"
            assert visual["role"] in {"condition", "solution"}
            assert visual["alt_text"].strip()
            figures.add(ATLAS / path)

    assert figures == set((ATLAS / "figures").glob("*.png"))
    for figure in figures:
        with Image.open(figure) as png:
            assert png.format == "PNG"
            png.verify()
