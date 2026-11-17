"""Shared scheduling guarantees without coupling geometry generators."""

from types import SimpleNamespace

import pytest

from app.math import oge15_scheduler, oge17_scheduler, oge18_scheduler


@pytest.mark.parametrize(
    ("module", "builder", "families"),
    [
        (oge15_scheduler, oge15_scheduler.build_task15_candidate_batch, ("a", "b")),
        (oge17_scheduler, oge17_scheduler.build_task17_candidate_batch, ("a", "b")),
        (oge18_scheduler, oge18_scheduler.build_task18_candidate_batch, ("a", "b")),
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
