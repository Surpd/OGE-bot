"""Exercise path routing and the single-PostgreSQL workflow contract."""

import yaml

from scripts.ci_select import classify, targets


def workflow():
    with open(".github/workflows/ci.yml", encoding="utf-8") as stream:
        return yaml.load(stream, Loader=yaml.BaseLoader)


def test_documentation_and_ui_only_need_fast():
    for paths in (["README.md", "docs/guide.md"], ["app/bot/progress_image.py"],
                  ["tests/test_progress_widget.py"]):
        result = classify(paths)
        assert not result["full"]
    assert "tests/test_progress_image.py" in targets(classify(["app/bot/progress_image.py"]))
    assert workflow()["jobs"]["fast"].get("services") is None


def test_numbered_math_requires_full_and_focused_fast():
    result = classify(["app/math/oge11_render.py"])
    assert result["numbers"] == [11] and result["full"] is True
    selected = targets(result)
    assert "tests/test_oge11_math.py" in selected
    assert "tests/test_oge11_postgres.py" not in selected  # covered by Full with PostgreSQL
    assert "tests/test_training_ux_contract.py" in selected


def test_story_changes_keep_linked_scenario_checks():
    for path in ("app/math/scenarios/stories/TYRES.py", "tests/test_tyres_story.py"):
        result = classify([path])
        assert result["full"] is True
        assert result["numbers"] == [1, 2, 3, 4, 5]
        assert any(node.startswith("tests/test_scenario_telegram.py::")
                   for node in targets(result))


def test_common_engine_database_and_unknown_changes_require_full():
    for path in ("app/bot/training_engine.py", "app/persistence/repository.py",
                 "app/math/answer_policy.py", "migrations/0001_foundation.sql",
                 "tests/conftest.py", "uv.lock", "unknown.py"):
        result = classify([path])
        assert result["code"] is True and result["full"] is True, path


def test_core_covers_public_menu_answer_and_history_without_database_skips():
    selected = targets(classify(["tests/test_task19_flow.py"]))
    assert "tests/test_training_ux_contract.py" in selected
    assert "tests/test_task19_flow.py" in selected
    assert any("test_memory_adapter_preserves_training" in node for node in selected)
    assert all(not node.endswith("_postgres.py") for node in selected)


def test_workflow_full_and_mass_are_disjoint_and_quality_checks_required_jobs():
    jobs = workflow()["jobs"]
    assert "pull_request" not in jobs["mass"]["if"]
    assert "inputs.profile == 'mass'" in jobs["mass"]["if"]
    assert "inputs.profile == 'full'" in jobs["full"]["if"]
    assert "needs.changes.outputs.full == 'true'" in jobs["full"]["if"]
    assert list(jobs["full"]["services"]) == ["postgres"]
    assert list(jobs["mass"]["services"]) == ["postgres"]
    assert jobs["full"]["concurrency"] == jobs["mass"]["concurrency"]
    assert jobs["full"]["concurrency"]["queue"] == "max"
    assert set(jobs["quality"]["needs"]) == {"changes", "fast", "full", "mass"}
    gate = jobs["quality"]["steps"][0]["run"]
    assert 'if [ "$FULL_REQUIRED" = true ]; then test "$FULL" = success; fi' in gate
