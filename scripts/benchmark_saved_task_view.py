"""Measure saved task verification and material preparation with synthetic sources."""

from __future__ import annotations

import asyncio
import json
from statistics import median
from time import perf_counter

from app.bot.error_replay import _materials
from app.math.inequalities import generate as inequality
from app.math.oge07_graph import generate_graph_problem
from app.math.oge11 import generate as graph
from app.math.oge17_generator import generate as quadrilateral
from app.math.oge18 import GENERATOR_VERSION_V2, VERSION_V3
from app.math.oge18 import generate as grid
from app.persistence.error_replay import load_replay_source
from app.persistence.repository import MemoryRepository


async def main() -> None:
    samples = {
        7: generate_graph_problem("OGE07-N01", 77_066).to_snapshot(),
        11: graph("OGE11-F01", 110_066).to_snapshot(),
        13: inequality("OGE13-S02", 130_066).to_snapshot(),
        17: quadrilateral("OGE17-R03", 170_066).to_snapshot(),
        18: grid(
            "OGE18-A04", 180_066, GENERATOR_VERSION_V2, renderer_version=VERSION_V3,
        ).to_snapshot(),
    }
    repository = MemoryRepository()
    timings = []
    for number, snapshot in samples.items():
        uid = number
        pid = str(snapshot["problem_id"])
        getattr(repository, f"issued{number}")[uid] = {pid: snapshot}
        getattr(repository, f"outcomes{number}")[uid] = {pid: "failed"}
        getattr(repository, f"attempts{number}")[uid] = [
            {"problem_id": pid, "attempt_no": 1, "is_correct": False}
        ]
        source_ms, materials_ms = [], []
        photos: tuple[bytes, ...] = ()
        for sample in range(8):
            started = perf_counter()
            source = await load_replay_source(repository, uid, f"o:{pid}")
            verified = perf_counter()
            _, photos = await asyncio.to_thread(_materials, source)
            done = perf_counter()
            if sample:
                source_ms.append((verified - started) * 1000)
                materials_ms.append((done - verified) * 1000)
        timings.append({
            "number": number,
            "verification_median_ms": round(median(source_ms), 2),
            "materials_median_ms": round(median(materials_ms), 2),
            "png_bytes": sum(map(len, photos)),
        })
    print(json.dumps(timings, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
