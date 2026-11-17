"""Cross-number state isolation and public gates after merging parallel geometry PRs."""

import pytest

from app.bot.trainings import BY_NUMBER
from app.math.oge15_triangles import generate as triangle
from app.math.oge16_circles import FAMILIES as CIRCLES
from app.math.oge16_circles import generate as circle
from app.math.oge17_generator import generate as quadrilateral
from app.math.oge18 import generate as grid
from app.persistence.repository import MemoryRepository


def test_geometry_public_gates_and_circle_inventory():
    assert len(CIRCLES) == 23
    assert BY_NUMBER[16].available
    assert BY_NUMBER[17].available
    assert BY_NUMBER[15].available
    assert BY_NUMBER[18].available


@pytest.mark.asyncio
async def test_geometry_sessions_keep_independent_snapshots_and_attempts():
    repository = MemoryRepository()
    snapshots = {
        15: triangle("OGE15-F01", 42).to_snapshot(),
        16: circle(CIRCLES[0], 42).to_snapshot(),
        17: quadrilateral("OGE17-R03", 42).to_snapshot(),
        18: grid("OGE18-M01", 42).to_snapshot(),
    }
    for number, snapshot in snapshots.items():
        await getattr(repository, f"ensure_task{number}_session")(42)
        await getattr(repository, f"advance_task{number}_problem")(42, None, [snapshot])
        await repository.save_user_state(42, f"task{number}")
        assert await getattr(repository, f"set_task{number}_condition_message")(
            42, snapshot["problem_id"], number * 100
        )
        await getattr(repository, f"task{number}_attempt")(
            42,
            snapshot["problem_id"],
            snapshot["correct_answer"],
            True,
            number * 100 + 1,
            number * 100,
        )
    for number, snapshot in snapshots.items():
        saved = await getattr(repository, f"task{number}_state")(42)
        assert saved["problem"] == snapshot
        progress = await getattr(repository, f"task{number}_progress")(42)
        assert progress["correct"] == progress["attempts"] == 1
