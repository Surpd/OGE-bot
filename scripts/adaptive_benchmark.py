"""Compare two checkouts against a disposable PostgreSQL database on localhost."""

import asyncio
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg

from app.bot.menu import main_menu
from app.math.oge9_scheduler import build_task9_candidate_batch
from app.persistence.repository import PostgresRepository
from app.persistence.training_insights import training_insights


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Use a disposable local database")
    adaptive = os.getenv("BENCH_ADAPTIVE") == "1"
    db = await asyncpg.connect(url)
    schema = "bench_" + uuid4().hex
    await db.execute(f"CREATE SCHEMA {schema}")
    samples = defaultdict(list)
    queries = []

    async def instrument(conn):
        conn.add_query_logger(queries.append)

    pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=1,
        init=instrument,
        server_settings={"search_path": schema, "bop.adaptive": "on" if adaptive else "off"},
    )

    async def measure(name, call):
        await asyncio.sleep(0)
        queries.clear()
        start = perf_counter()
        await call()
        stop = perf_counter()
        await asyncio.sleep(0)
        samples[name].append(((stop - start) * 1000, len(queries)))

    try:
        for path in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(path.read_text())
        repo = PostgresRepository(pool)
        user = 804
        await repo.ensure_task9_session(user)
        previous = None
        for i in range(32):
            p = await repo.advance_task9_problem(
                user, previous, build_task9_candidate_batch({}, 209 + i)
            )
            previous = str(p["problem_id"])
            await repo.save_user_state(user, "task9")

            async def answer(previous=previous, p=p, i=i):
                await repo.task9_attempt(user, previous, str(p["correct_answer"]), True, 100 + i)
                if adaptive:
                    from app.adaptive.store import sync

                    async with pool.acquire() as conn, conn.transaction():
                        owner = await conn.fetchval(
                            """SELECT id FROM users u WHERE telegram_user_id=$1
                            AND EXISTS(SELECT FROM adaptive_dirty WHERE owner=u.id)""",
                            user,
                        )
                        if owner:
                            await sync(conn, owner)

            async def menu():
                from app.bot.router import _has_resumable_session

                main_menu(has_session=await _has_resumable_session(repo, user))
                if adaptive:
                    from app.adaptive.store import menu_available

                    await menu_available(repo, user)

            async def progress():
                await training_insights(repo, user, "summary")
                if adaptive:
                    from app.adaptive.store import overview

                    await overview(repo, user)

            async def personal():
                from datetime import UTC, datetime

                from app.adaptive.planner import plan
                from app.adaptive.store import overview
                from app.bot.adaptive import catalog

                plan(await overview(repo, user), catalog(), datetime.now(UTC).timestamp())

            await measure("answer", answer)
            await measure("menu", menu)
            await measure("progress", progress)
            if adaptive:
                await measure("plan", personal)
        result = {}
        for k, data in samples.items():
            elapsed, counts = zip(*data[2:], strict=True)
            result[k] = {
                "median_ms": round(statistics.median(elapsed), 2),
                "p95_ms": round(sorted(elapsed)[28], 2),
                "median_queries": statistics.median(counts),
            }
        if adaptive:
            result["bytes_32_tasks"] = await pool.fetchval("""SELECT
                (SELECT sum(pg_column_size(e)) FROM adaptive_evidence e)+
                (SELECT sum(pg_column_size(s)) FROM adaptive_skills s)""")
        print(json.dumps(result))
    finally:
        await pool.close()
        await db.execute(f"DROP SCHEMA {schema} CASCADE")
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
