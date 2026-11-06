"""Unit gates for the GitHub-only coordinator; no network or production services."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_handoff", ROOT / "scripts/agent_handoff.py")
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


@pytest.fixture
def sample():
    return json.loads((ROOT / "tests/fixtures/pr33_agent_handoff.json").read_text(encoding="utf-8"))


def assess(sample):
    return module.evaluate(sample["pr"], sample["ci_run"], sample["jobs"],
                           sample["reviews"], sample["previous"])


def test_pr33_real_metadata_model_is_waiting_for_independent_review(sample):
    result = assess(sample)
    assert result.status == "awaiting_independent_review"
    assert result.ci_conclusion == "success"
    assert result.repair_cycles == 0
    assert module.parse_state(module.render_comment(result)) == result.as_dict()


def test_current_independent_approval_enables_only_human_acceptance(sample):
    sample["reviews"] = [{"id": 1, "user": {"login": "Reviewer"}, "state": "APPROVED",
                          "commit_id": sample["pr"]["head"]["sha"],
                          "submitted_at": "2026-11-06T12:00:00Z"}]
    decision = assess(sample)
    assert decision.status == "ready_for_human_acceptance"
    assert not decision.as_dict()["production_release_allowed"]
    assert not decision.as_dict()["executor_connected"]


def test_author_self_review_is_not_independent(sample):
    sample["reviews"] = [{"id": 1, "user": {"login": "Surpd"}, "state": "APPROVED",
                          "commit_id": sample["pr"]["head"]["sha"]}]
    assert assess(sample).status == "awaiting_independent_review"


def test_stale_approval_is_not_accepted(sample):
    sample["reviews"] = [{"id": 1, "user": {"login": "Reviewer"}, "state": "APPROVED",
                          "commit_id": "old-sha"}]
    assert assess(sample).status == "awaiting_independent_review"


def test_requested_changes_block_despite_earlier_approval(sample):
    sample["reviews"] = [
        {"id": 1, "user": {"login": "Reviewer"}, "state": "APPROVED",
         "commit_id": sample["pr"]["head"]["sha"], "submitted_at": "2026-11-06T10:00:00Z"},
        {"id": 2, "user": {"login": "Reviewer"}, "state": "CHANGES_REQUESTED",
         "commit_id": sample["pr"]["head"]["sha"], "submitted_at": "2026-11-06T11:00:00Z"}]
    assert assess(sample).status == "blocked_review"


@pytest.mark.parametrize("bad_job", ["quality", "oge15-linux-render"])
def test_missing_or_failed_mandatory_job_fails_closed(sample, bad_job):
    sample["jobs"] = [job for job in sample["jobs"] if job["name"] != bad_job]
    assert assess(sample).status == "blocked_ci"
    sample["jobs"].append({"name": bad_job, "status": "completed", "conclusion": "failure"})
    assert assess(sample).status == "blocked_ci"


def test_stale_workflow_run_cannot_update_current_head(sample):
    sample["ci_run"]["head_sha"] = "old-sha"
    with pytest.raises(ValueError, match="stale"):
        assess(sample)


def test_explicit_block_dominates_successful_ci(sample):
    sample["pr"]["labels"] = [{"name": "agent:blocked"}]
    assert assess(sample).status == "blocked_manual"


def test_repair_budget_is_preserved_and_limited(sample):
    assert [module.next_repair_cycle(i) for i in range(3)] == [1, 2, 3]
    with pytest.raises(ValueError):
        module.next_repair_cycle(3)
    sample["ci_run"]["conclusion"] = "failure"
    sample["previous"] = {"schema_version": 1, "pr_number": 33, "repair_cycles": 3}
    assert assess(sample).status == "blocked_max_repairs"
    with pytest.raises(ValueError):
        module.previous_cycles({"schema_version": 1, "pr_number": 33,
                                "repair_cycles": -1}, 33)


def test_comment_replay_and_bot_identity():
    example = {"id": 17, "user": {"login": module.BOT_LOGIN},
               "body": module.MARKER + "\n```json\n"
               + json.dumps({"schema_version": 1, "pr_number": 33, "repair_cycles": 1})
               + "\n```"}
    assert module.find_bot_state([example]) == (17, {"schema_version": 1,
                                                     "pr_number": 33, "repair_cycles": 1})
    assert module.find_bot_state([{**example, "user": {"login": "attacker"}}]) == (None, None)
    with pytest.raises(ValueError, match="multiple"):
        module.find_bot_state([example, {**example, "id": 18}])


def test_unfinished_ci_does_not_pass(sample):
    sample["ci_run"]["status"] = "in_progress"
    sample["ci_run"]["conclusion"] = None
    assert assess(sample).status == "awaiting_ci"
