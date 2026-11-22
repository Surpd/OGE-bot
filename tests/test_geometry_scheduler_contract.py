"""Shared scheduling guarantees without coupling geometry generators."""

from types import SimpleNamespace

import pytest

from app.math import oge15_scheduler, oge17_scheduler, oge18_scheduler


@pytest.mark.parametrize(
    ("module", "builder", "families"),
    [
        (oge15_scheduler, oge15_scheduler.build_task15_candidate_batch, ("a", "b")),
        (oge17_scheduler, oge17_scheduler.build_task17_candidate_batch, ("a", "b")),
    ],
)
def test_scheduler_skips_recent_and_reports_actual_bounded_attempts(
    monkeypatch, module, builder, families
):
    calls = []

    def generate(family, *args, **kwargs):
        calls.append(family)
        fingerprint = "old" if family == "a" else "new"
        return SimpleNamespace(
            fingerprint=fingerprint,
            to_snapshot=lambda: {"family_id": family, "fingerprint": fingerprint},
        )

    monkeypatch.setattr(module, "generate", generate)
    state = {"family_queue": ["a", "b"], "recent_fingerprints": ["old"]}
    result = builder(state, 42, enabled_families=families)
    assert calls == ["a"] * 12 + ["b"]
    assert result[0]["family_id"] == "b"
    assert result[0]["selection_attempts"] == 13
    assert result[0]["_family_queue_after"] == []
    assert state["family_queue"] == ["a", "b"]

    assert builder(state, 42, enabled_families=("a",)) == []
    assert len(calls) == 25


def test_grid_scheduler_skips_exhausted_shapes_before_rendering(monkeypatch):
    from unittest.mock import Mock

    from app.math.oge18 import GENERATOR_VERSION_V2, _model_for_seed, fingerprint

    distance, area = "OGE18-D05", "OGE18-A03"
    seen = {
        fingerprint(distance, _model_for_seed(distance, seed, GENERATOR_VERSION_V2)[0])
        for seed in range(100)
    }
    assert len(seen) == 3
    state = {"family_queue": [distance, area], "recent_fingerprints": sorted(seen)}
    render = Mock(wraps=oge18_scheduler.generate)
    monkeypatch.setattr(oge18_scheduler, "generate", render)
    build = oge18_scheduler.build_task18_candidate_batch
    (result,) = build(state, 42, enabled_families=(distance, area))
    assert (result["family_id"], result["selection_attempts"]) == (area, 1)
    assert result["fingerprint"] not in seen
    assert result["_family_queue_after"] == [distance]
    assert state["family_queue"] == [distance, area]
    render.assert_called_once()
    # Once the alternative has been served, the outstanding type must still
    # finish the cycle. It reuses its least recently shown shape.
    (last,) = build({**state, "family_queue": result["_family_queue_after"]}, 42,
                    enabled_families=(distance, area))
    assert last["family_id"] == distance
    assert last["fingerprint"] == state["recent_fingerprints"][0]
    assert last["_family_queue_after"] == []
    assert render.call_count == 2
