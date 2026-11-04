from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import statistics
import time
from functools import partial
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg

from app.bot.math_image import render_math_image
from app.main import _run_schema_migrations
from app.math.inequalities import generate as generate_inequality
from app.math.inequalities import render_option_sheet_snapshot_png
from app.math.oge07_graph import GRAPH_SOURCES
from app.math.oge07_scheduler import build_task7_candidate_batch
from app.math.oge11 import ENABLED_FAMILIES as TASK11_FAMILIES
from app.math.oge11 import generate as generate_task11
from app.math.oge11 import verify as verify_task11
from app.math.oge11_scheduler import build_task11_candidate_batch
from app.math.oge13_scheduler import build_task13_candidate_batch
from app.persistence.repository import PostgresRepository


def _measure(function):
    started = time.perf_counter()
    value = function()
    return (time.perf_counter() - started) * 1000, value


async def _measure_async(function):
    started = time.perf_counter()
    value = await function()
    return (time.perf_counter() - started) * 1000, value


def _issue_candidates(builder, state, seed):
    if "limit" in inspect.signature(builder).parameters:
        return builder(state, seed, limit=1)
    return builder(state, seed)


def _stats(samples):
    return {
        "median_ms": round(statistics.median(samples), 2),
        "samples_ms": [round(value, 2) for value in samples],
    }


def _profile_candidates(builder, state, seed, repeats):
    samples = []
    counts = []
    base64_chars = []
    for offset in range(repeats):
        elapsed, items = _measure(
            lambda offset=offset: _issue_candidates(builder, state, seed + offset)
        )
        samples.append(elapsed)
        counts.append(len(items))
        base64_chars.append(
            sum(
                len(str(item.get(key, "")))
                for item in items
                for key in ("png_base64", "graph_png_base64")
            )
        )
    return {"elapsed": _stats(samples), "count": counts, "png_base64_chars": base64_chars}


async def run(database_url: str, repeats: int, seed: int) -> None:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/").lower()
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("benchmark requires an isolated local PostgreSQL server")
    if not any(marker in database_name for marker in ("test", "bench", "ci")):
        raise ValueError("benchmark database name must identify a test/bench database")

    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    repository = PostgresRepository(pool)
    report = {
        "postgres": await pool.fetchval("SHOW server_version"),
        "repeats": repeats,
        "seed": seed,
        "scenarios": {},
    }
    try:
        await _run_schema_migrations(pool)
        graph_family = next(iter(GRAPH_SOURCES))
        task7_builder = partial(build_task7_candidate_batch, family_ids=(graph_family,))
        task11_builder = partial(build_task11_candidate_batch, enabled_families=TASK11_FAMILIES)
        task13_builder = build_task13_candidate_batch
        task7 = _profile_candidates(task7_builder, {}, seed, repeats)
        task11 = _profile_candidates(task11_builder, {}, seed + 100, repeats)
        task13 = _profile_candidates(task13_builder, {}, seed + 200, repeats)
        report["scenarios"]["task7_graph_candidate_preparation"] = {
            **task7,
            "family": graph_family,
        }
        report["scenarios"]["task11_candidate_preparation"] = {
            **task11,
            "family_count": len(TASK11_FAMILIES),
        }
        report["scenarios"]["task13_candidate_preparation"] = task13

        generation_samples = []
        verification_samples = []
        problem = generate_task11(TASK11_FAMILIES[0], seed + 300)
        snapshot = problem.to_snapshot()
        for offset in range(repeats):
            elapsed, _ = _measure(
                lambda offset=offset: generate_task11(TASK11_FAMILIES[0], seed + 310 + offset)
            )
            generation_samples.append(elapsed)
            elapsed, _ = _measure(lambda: verify_task11(problem))
            verification_samples.append(elapsed)
        report["scenarios"]["task11_one_problem"] = {
            "generate_including_png_and_oracle": _stats(generation_samples),
            "repeat_oracle": _stats(verification_samples),
            "png_bytes": len(problem.png_bytes),
            "snapshot_base64_chars": len(str(snapshot.get("png_base64", ""))),
        }

        task13_snapshot = generate_inequality("OGE13-S01", seed + 400).to_snapshot()
        png_samples = []
        for _ in range(repeats):
            elapsed, _ = _measure(lambda: render_option_sheet_snapshot_png(task13_snapshot))
            png_samples.append(elapsed)
        report["scenarios"]["task13_saved_options_png"] = {
            "snapshot_validation_and_render": _stats(png_samples),
            "png_bytes": len(render_option_sheet_snapshot_png(task13_snapshot)),
        }

        database_samples = {}
        user_ids = []
        try:
            requests = (
                (
                    "task7",
                    task7_builder,
                    repository.ensure_task7_session,
                    repository.advance_task7_problem,
                ),
                (
                    "task11",
                    task11_builder,
                    repository.ensure_task11_session,
                    repository.advance_task11_problem,
                ),
                (
                    "task13",
                    task13_builder,
                    repository.ensure_task13_session,
                    repository.advance_task13_problem,
                ),
            )
            for index, (mode, builder, ensure, advance) in enumerate(requests):
                user_id = int(uuid4().int % (2**62)) + 1
                user_ids.append(user_id)
                await ensure(user_id)
                candidates = _issue_candidates(builder, {}, seed + 500 + index)
                elapsed, _ = await _measure_async(
                    lambda advance=advance, user_id=user_id, candidates=candidates: advance(
                        user_id, None, candidates
                    )
                )
                database_samples[mode] = round(elapsed, 2)
        finally:
            for user_id in user_ids:
                await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        report["postgres_issue_insert_ms"] = database_samples

        formula = "Задание №11\nСопоставьте формулы и графики.\ny = 2x + 1"
        render_samples = []
        image = b""
        for _ in range(repeats):
            elapsed, image = _measure(lambda: render_math_image(formula))
            render_samples.append(elapsed)
        report["scenarios"]["formula_png_fallback"] = {
            "layout_and_render": _stats(render_samples),
            "png_bytes": len(image),
        }
        report["limitations"] = [
            "Telegram and tap-to-visible timings need a live token.",
            "PG timings use isolated local PostgreSQL 17 and exclude schema setup.",
            "The render fallback timing is local and may vary with Matplotlib cold-start state.",
        ]
    finally:
        await pool.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=70_000)
    options = parser.parse_args()
    if not options.database_url:
        parser.error("set DATABASE_URL to an isolated PostgreSQL 17 database")
    asyncio.run(run(options.database_url, options.repeats, options.seed))
