"""Route PR checks; unknown production changes require full regression."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Explicit node IDs keep Fast independent of PostgreSQL: the same files also
# contain integration tests, which run in Full against PostgreSQL 17.
CORE = (
    "tests/test_training_ux_contract.py",
    "tests/test_scenario_engine.py",
    "tests/test_scenario_telegram.py::test_oge15_public_number_menu_and_story_exclusions",
    "tests/test_scenario_telegram.py::test_public_registry_is_explicit_and_excludes_unconfirmed_or_blocked_families",
    "tests/test_task19_flow.py",
    "tests/test_training_insights.py::test_solved_metrics_use_terminal_outcome_and_attempt_time_assistance",
    "tests/test_training_insights.py::test_memory_adapter_preserves_training_and_separates_users",
    "tests/test_training_insights.py::test_memory_pages_keep_unknown_old_results_and_bound_history",
    "tests/test_webhook.py::test_update_is_idempotent",
    "tests/test_ci_selection.py",
)
MATH_MODULES = {
    "generator": 6, "registry": 6, "problem": 6, "scheduler": 6,
    "numbers": 7, "oge8": 8, "equations": 9, "probability": 10,
    "oge11": 11, "formulas": 12, "inequalities": 13, "progressions": 14,
}
# Presentation-only changes get Fast; lifecycle/navigation and data paths are Full.
UI_TESTS = {
    "app/bot/menu.py": ("tests/test_navigation.py",),
    "app/bot/presentation.py": (
        "tests/test_math_presentation.py", "tests/test_rich_math_runtime.py",
    ),
    "app/bot/math_fragments.py": ("tests/test_math_fragments.py",),
    "app/bot/progress.py": ("tests/test_progress_image.py", "tests/test_progress_widget.py"),
    "app/bot/progress_image.py": ("tests/test_progress_image.py",),
    "app/bot/progress_widget.py": ("tests/test_progress_widget.py",),
}


def _db_test(path: str) -> bool:
    """Route mixed PostgreSQL test files to Full, not skipped tests in Fast."""
    if "postgres" in Path(path).name or path == "tests/test_migrations_startup.py":
        return True
    file = ROOT / path
    if not file.is_file():
        return True  # deleted/unknown test: conservative full run
    text = file.read_text(encoding="utf-8").lower()
    return any(word in text for word in ("database_url", "asyncpg", "postgres", "insights_pool"))


def classify(paths: list[str]) -> dict[str, object]:
    numbers: set[int] = set()
    tests: set[str] = set()
    full = False
    code = False
    for path in paths:
        if path.endswith(".md") and not path.startswith(".github/"):
            continue
        code = True
        name = Path(path).name
        stem = Path(path).stem
        match = re.search(r"(?:oge|task)0?(1[0-9]|[6-9])(?:_|\.|$)", name)
        if match:
            numbers.add(int(match.group(1)))
        elif path.startswith("app/math/scenarios/") or stem == "scenario_engine":
            numbers.update(range(1, 6))
        elif path.startswith("app/math/") and stem in MATH_MODULES:
            numbers.add(MATH_MODULES[stem])
        elif path.startswith("tests/") and any(
            word in stem for word in ("scenario", "story", "adapter")
        ):
            numbers.update(range(1, 6))

        if path.startswith("tests/") and name.startswith("test_") and path.endswith(".py"):
            if _db_test(path):
                full = True
            else:
                tests.add(path)
            # Math and scenario test changes also protect generators/oracles.
            if match or any(word in stem for word in ("scenario", "story", "adapter")):
                full = True
        elif path.startswith("tests/"):
            full = True
        elif path in UI_TESTS:
            tests.update(UI_TESTS[path])
        elif path.startswith(("app/", "migrations/", ".github/", "scripts/", "atlas/")):
            full = True
        else:
            full = True  # dependencies, fixtures and unknown production files
    return {"code": code, "full": full, "numbers": sorted(numbers), "tests": sorted(tests)}


def changed_files(base: str, head: str = "HEAD") -> list[str]:
    data = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"], cwd=ROOT
    )
    return [item.decode("utf-8") for item in data.split(b"\0") if item]


def targets(result: dict[str, object]) -> list[str]:
    paths = set(CORE)
    for number in result["numbers"]:  # type: ignore[union-attr]
        if number <= 5:
            patterns = ("test_*story*.py", "test_*adapter.py", "test_scenario*.py",
                        "test_oge15_*.py")
        else:
            patterns = (f"test_oge{number:02d}*.py", f"test_oge{number}*.py",
                        f"test_task{number}_*.py")
        for pattern in patterns:
            paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob(pattern)
                         if not _db_test(p.relative_to(ROOT).as_posix()))
    paths.update(result["tests"])  # type: ignore[arg-type]
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("classify", "fast"))
    parser.add_argument("base", nargs="?")
    args = parser.parse_args()
    # A missing base fails closed: core Fast plus Full, never a docs-only result.
    result = classify(changed_files(args.base)) if args.base else {
        "code": True, "full": True, "numbers": [], "tests": [],
    }
    if args.mode == "classify":
        for key in ("code", "full"):
            print(f"{key}={str(result[key]).lower()}")
        print("numbers=" + ",".join(map(str, result["numbers"])))  # type: ignore[arg-type]
        return 0
    command = [sys.executable, "-m", "pytest", "-q", "-m", "not mass", "--durations=10"]
    command.extend(targets(result))
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
