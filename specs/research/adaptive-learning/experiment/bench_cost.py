"""Local cost probes. SQLite figures are not PostgreSQL estimates."""

import json
import sqlite3
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter_ns

from adapter import Adapter
from model import Engine


def profile_queue(count):
    engine = Engine(skills=range(count))
    for i, skill in engine.skills.items():
        skill.stage = ("unknown", "confirmed", "practice")[i % 3]
        skill.due = 7 if i % 3 == 1 else None
        skill.last_offer = i % 11
    times = []
    for _ in range(1000):
        start = perf_counter_ns()
        engine.queue(30)
        times.append((perf_counter_ns() - start) / 1000)
    return {
        "skills": count,
        "repetitions": len(times),
        "median_us": statistics.median(times),
        "p95_us": sorted(times)[949],
    }


def profile_delivery():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "observations.sqlite"
        adapter = Adapter(path, {(0, 0), (0, 1)})
        initial = path.stat().st_size
        trace = []
        adapter.db.set_trace_callback(trace.append)
        first = adapter.issue("student", 0, 0, "original", check_eligible=True)
        issue_calls = len(trace)
        trace.clear()
        adapter.record("student", first, 0, "u", 0, "correct")
        answer_calls = len(trace)
        adapter.db.set_trace_callback(None)
        for n in range(1, 400):
            task = adapter.issue("student", 0, n % 2, f"sample-{n:04}", check_eligible=True)
            adapter.record("student", task, 0, str(n), n * 86400, "correct")
        total = path.stat().st_size
        adapter.db.close()
        return {
            "observations": 400,
            "bytes_initial": initial,
            "bytes_final": total,
            "nominal_bytes_per_additional_observation": (total - initial) / 400,
            "sql_statements_first_issue_including_tx": issue_calls,
            "sql_statements_first_submission_including_tx": answer_calls,
        }


if __name__ == "__main__":
    report = {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "queues": [profile_queue(n) for n in (25, 250, 1000)],
        "delivery": profile_delivery(),
    }
    encoded = json.dumps(report, indent=2)
    print(encoded)
    Path(__file__).with_name("local_cost.json").write_text(encoded + "\n", encoding="utf8")
