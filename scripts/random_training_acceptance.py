"""Offline sequences through Telegram's ordinary handlers and committed Mix transitions."""

import argparse
import asyncio
import json
import random
import secrets
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram.types import User

from app.bot import mixed_training, router
from app.bot.training_engine import NUMERIC_TRAININGS, send_problem
from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import MemoryRepository


async def run(number, seed, route, turns=100):
    repo = MemoryRepository()
    owner = seed + number
    message = AsyncMock()
    message.from_user = User(id=owner, is_bot=False, first_name="Demo")
    message.message_id = 100
    message.answer.return_value.message_id = message.answer_photo.return_value.message_id = 101
    message.reply_to_message = None
    ordinary = getattr(
        router, "_send_problem" if number == 6 else f"_send_task{number}_problem", None
    )
    store = MixedTrainingRepository(repo)
    await store.start(owner, [number])
    previous = {}
    seq = []
    with patch.object(secrets, "randbelow", random.Random(seed + number).randrange):
        for turn in range(turns):
            mode = ("ordinary" if turn % 2 == 0 else "mix") if route == "switch" else route
            start = time.perf_counter()
            refusals = 0
            last = previous.get(mode)
            if mode == "ordinary":
                opts = dict(
                    action="advance" if last else "start",
                    expected_problem_id=last,
                    skip_active=bool(last),
                )
                if ordinary:
                    assert await ordinary(message, repo, **opts)
                else:
                    assert await send_problem(NUMERIC_TRAININGS[number], message, repo, **opts)
                problem = (await getattr(repo, f"task{number}_state")(owner))["problem"]
            elif last:
                assert await store.action(owner, last, "skip")
                state = (await store.state(owner))["state"]
                local = state.get("generator_states", {}).get(str(number), {})
                prepared = await store.candidate_state(owner, number, local)
                for _ in range(10):
                    try:
                        candidate = mixed_training._candidate(number, prepared)
                        break
                    except RuntimeError as exc:
                        if "No public candidates" not in str(exc):
                            raise
                        refusals += 1
                else:
                    return seq
                problem = await store.advance(owner, last, candidate, number, new_cycle=[number])
            else:
                problem = await mixed_training._issue(store, owner)
            assert problem and last != problem["problem_id"]
            previous[mode] = problem["problem_id"]
            seq.append(
                [
                    problem["family_id"],
                    problem["fingerprint"],
                    round(1000 * (time.perf_counter() - start), 2),
                    refusals,
                ]
            )
            message.answer.reset_mock()
            message.answer_photo.reset_mock()
    return seq


async def main(args):
    result = {}
    for number in args.numbers:
        for mode in args.modes:
            for seed in args.seeds:
                result[f"{number}/{mode}/{seed}"] = await run(number, seed, mode)
        args.output.write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--numbers", nargs="+", type=int, default=list(range(6, 20)))
    parser.add_argument("--modes", nargs="+", default=["ordinary", "mix", "switch"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[20261121, 20261122])
    asyncio.run(main(parser.parse_args()))
