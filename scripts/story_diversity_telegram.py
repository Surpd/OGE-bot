"""Exercise successive exact-family issues through the offline Telegram dispatcher."""
import asyncio
import csv
from pathlib import Path

from scripts import live_training_acceptance as live
from scripts.story_diversity_acceptance import BASELINE, OUT

CAPTURE = {
    "GARDEN-04-PERIMETER-POLYGON", "FLAT-03-RECT-AREA", "PAPER-F04", "TARIFF-F09-PERCENT-FEE",
}


async def exercise(h):
    report = live.Report(h)
    session = live.Session(h.repository, 42)
    rows = []
    with BASELINE.open(encoding="utf-8") as stream:
        families = list(csv.DictReader(stream))
    for row in families:
        family = row["family"]
        h.transport.messages.clear()
        await h.message("/start")
        await h.click("nav:trainings")
        await h.click("train:areas")
        await live.access_family(h, int(row["position"]), family)
        report.cursor = len(h.transport.calls)
        await h.click(f"train:family:{family}")
        seen = set()
        for i in range(10):
            active = await session.current()
            assert active and active["position"] == i and active["problem"], (
                family, i, [(c.__api_method__, getattr(c, "text", None))
                            for c in h.transport.calls[-5:]],
            )
            data = live.problem_data(active)
            assert data["family_id"] == family and data["fingerprint"] not in seen, (family, i)
            seen.add(data["fingerprint"])
            if family in CAPTURE and i < 2:
                await report.mark(f"{family}-{i+1}", f"{family} · выдача {i+1}")
                await h.click(f"ad:data:{active['problem']}")
                await report.mark(f"{family}-{i+1}-data", f"{family} · повторное открытие данных")
            await h.message(str(data["correct_answer"]))
            report.cursor = len(h.transport.calls)
            if i < 9:
                advance = "continue" if i == 4 else "next"
                await h.click(f"ad:{advance}:{active['problem']}")
        totals = await session.totals(active["id"])
        assert totals["independent"] == totals["solved"] == len(seen) == 10
        await h.click(f"ad:finish:{active['problem']}")
        rows.append((family, len(seen), totals["independent"]))
        print(family, len(seen), flush=True)
        h.transport.calls.clear()
        report.cursor = 0
    report.write()
    with (OUT / "sequential.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("family", "distinct_issues", "independent_answers"))
        writer.writerows(rows)


if __name__ == "__main__":
    live.OUT = Path("reports/story-diversity/telegram")
    asyncio.run(live.run_with_synthetic_user(exercise))
