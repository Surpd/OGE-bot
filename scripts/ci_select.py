"""Select conservative PR checks; unknown paths fall back to broad regressions."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    "tests/test_training_ux_contract.py",
    "tests/test_scenario_engine.py",
    "tests/test_task19_flow.py",
    "tests/test_training_insights.py",
    "tests/test_webhook.py",
    "tests/test_ci_selection.py",
)
# Files without a number in their name; anything unknown under app/math is broad.
MATH_MODULES = {
    "generator": 6, "registry": 6, "problem": 6, "scheduler": 6,
    "numbers": 7, "oge8": 8, "equations": 9, "probability": 10,
    "oge11": 11, "formulas": 12, "inequalities": 13, "progressions": 14,
}


def name_is_test(path: str) -> bool:
    return Path(path).name.startswith("test_") and path.endswith(".py")


def classify(paths: list[str]) -> dict[str, object]:
    numbers: set[int] = set()
    tests: set[str] = set()
    broad = False
    mass = False
    code = False
    for path in paths:
        # Only prose is considered documentation. Config, fixtures and atlas data
        # can alter runtime/testing and must never silently bypass checks.
        if path.endswith(".md") and not path.startswith(".github/"):
            continue
        code = True
        if path.startswith(("app/math/", "atlas/", "specs/research/", "scripts/oge")):
            mass = True
        if path.startswith("tests/") and name_is_test(path):
            tests.add(path)
        elif path.startswith("tests/"):
            broad = True
        name = Path(path).name
        stem = Path(path).stem
        match = re.search(r"(?:oge|task)0?(1[0-9]|[6-9])(?:_|\.|$)", name)
        if match:
            numbers.add(int(match.group(1)))
            if path.startswith("tests/"):
                mass = True
        elif (path.startswith("app/math/scenarios/") or stem == "scenario_engine"
              or (path.startswith("tests/") and any(
                  token in stem for token in ("scenario", "story", "adapter")
              ))):
            numbers.update(range(1, 6))
            mass = True
        elif path.startswith("app/math/") and stem in MATH_MODULES:
            numbers.add(MATH_MODULES[stem])
        elif path.startswith(("app/", "migrations/", ".github/", "scripts/", "atlas/")):
            broad = True
            if path.startswith((".github/", "scripts/ci_")):
                mass = True
        elif not path.startswith("tests/"):
            broad = True
            if path in {"pyproject.toml", "uv.lock"}:
                mass = True
    return {"code": code, "mass": mass, "broad": broad, "numbers": sorted(numbers),
            "tests": sorted(tests)}


def changed_files(base: str, head: str = "HEAD") -> list[str]:
    # Diff both old and new names, including deleted files. Failure must fail CI.
    data = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}"], cwd=ROOT
    )
    return [item.decode("utf-8") for item in data.split(b"\0") if item]


def targets(result: dict[str, object]) -> list[str]:
    if result["broad"]:
        return []  # all tests, excluding only explicitly marked mass tests
    paths = set(CORE)
    for number in result["numbers"]:  # type: ignore[union-attr]
        if number <= 5:
            patterns = ("test_*story*.py", "test_*adapter.py", "test_scenario*.py",
                        "test_oge15_*.py")
        else:
            patterns = (f"test_oge{number:02d}*.py", f"test_oge{number}*.py",
                        f"test_task{number}_*.py")
        for pattern in patterns:
            paths.update(p.as_posix() for p in Path("tests").glob(pattern))
    paths.update(path for path in result["tests"] if Path(path).is_file())  # type: ignore[union-attr]
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("classify", "fast"))
    parser.add_argument("base")
    args = parser.parse_args()
    result = classify(changed_files(args.base))
    if args.mode == "classify":
        for key in ("code", "mass", "broad"):
            print(f"{key}={str(result[key]).lower()}")
        print("numbers=" + ",".join(map(str, result["numbers"])))  # type: ignore[arg-type]
        return 0
    command = [sys.executable, "-m", "pytest", "-q", "-m", "not mass", "--durations=10"]
    command.extend(targets(result))
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
