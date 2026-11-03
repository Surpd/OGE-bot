"""Run a focused pytest group without repeating the full CI suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBERED_MATH = {
    str(number): f"tests/test_oge{number:02d}_math.py" for number in (7, 8, 9, 10, 11, 12, 13, 14)
}
NUMBERED_MATH["6"] = "tests/test_oge6_quality.py"

PRESETS: dict[str, list[str]] = {
    "ui": ["tests/test_training_ux_contract.py", "tests/test_task*_flow.py"],
    "presentation": [
        "tests/test_math_presentation.py",
        "tests/test_math_fragments.py", "tests/test_rich_math_runtime.py",
        "tests/test_*typesetting*.py",
    ],
    "navigation": [
        "tests/test_navigation.py",
        "tests/test_navigation_postgres.py",
        "tests/test_family_selection.py",
        "tests/test_answer_send_order.py",
    ],
    "progress": ["tests/test_training_insights.py"],
    "db": ["tests/*_postgres.py", "tests/test_migrations_startup.py", "tests/test_webhook.py"],
    "all": [],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "preset",
        choices=(*PRESETS, "math-number"),
        help="Focused test group; 'all' runs the complete pytest suite.",
    )
    parser.add_argument(
        "number",
        nargs="?",
        choices=tuple(NUMBERED_MATH),
        help="Required for a single math-number run (6–14).",
    )
    parser.add_argument("-k", dest="keyword", help="Forward a pytest -k expression.")
    args = parser.parse_args()

    if args.preset == "math-number":
        if args.number is None:
            parser.error("math-number requires a number from 6 through 14")
        patterns = [NUMBERED_MATH[args.number]]
    else:
        if args.number is not None:
            parser.error("a number is only valid with the math-number preset")
        patterns = PRESETS[args.preset]

    targets: list[str] = []
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            targets.extend(
                path.relative_to(ROOT).as_posix()
                for path in ROOT.glob(pattern)
                if path.is_file()
            )
        elif (ROOT / pattern).is_file():
            targets.append(pattern)
        else:
            parser.error(f"requested test file does not exist: {pattern}")
    targets = sorted(set(targets))
    if args.preset != "all" and not targets:
        parser.error(f"preset '{args.preset}' did not match any test files")

    command = [sys.executable, "-m", "pytest", "-q"]
    command.extend(targets)
    if args.keyword:
        command.extend(("-k", args.keyword))
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
