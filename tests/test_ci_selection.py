"""CI path routing is fail-closed for code and shared dependencies."""

from scripts.ci_select import classify, targets


def test_docs_only_does_not_start_postgres_or_full_suite():
    assert classify(["README.md", "docs/guide.md"])["code"] is False
    assert classify(["README.md", "pyproject.toml"])["code"] is True


def test_generator_change_selects_number_and_mass_qa():
    result = classify(["app/math/oge11_render.py"])
    assert result["numbers"] == [11] and result["mass"] is True
    assert "tests/test_oge11_math.py" in targets(result)
    assert "tests/test_oge11_postgres.py" in targets(result)
    assert "tests/test_training_ux_contract.py" in targets(result)


def test_story_changes_keep_linked_scenario_checks_and_mass():
    for path in ("app/math/scenarios/stories/TYRES.py", "tests/test_tyres_story.py"):
        result = classify([path])
        assert result["mass"] is True
        assert result["numbers"] == [1, 2, 3, 4, 5]
        assert "tests/test_scenario_telegram.py" in targets(result)


def test_common_engine_database_and_answer_policy_expand_regressions():
    for path in ("app/bot/training_engine.py", "app/persistence/repository.py",
                 "app/math/answer_policy.py", "migrations/0001_foundation.sql",
                 "tests/conftest.py", "uv.lock", "unknown.py"):
        result = classify([path])
        assert result["code"] is True and result["broad"] is True, path
        assert targets(result) == []  # pytest with no paths runs the entire non-mass suite


def test_public_menu_answer_and_history_are_always_in_core():
    result = classify(["tests/test_task19_flow.py"])
    selected = targets(result)
    assert "tests/test_training_ux_contract.py" in selected
    assert "tests/test_task19_flow.py" in selected
    assert "tests/test_training_insights.py" in selected
    assert "tests/test_webhook.py" in selected
