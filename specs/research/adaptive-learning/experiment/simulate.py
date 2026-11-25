"""Paired synthetic experiment. Standard library only. No production dependencies."""

import argparse
import csv
import json
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

from model import Engine, Event

HERE = Path(__file__).resolve().parent
POLICIES = ("rules", "weighted", "bkt")
# initial proficiency, attendance, slip, hint, memory, quit per offered task
PROFILES = {
    "A": (0.91, 0.88, 0.03, 0.04, 0.4, 0.02),
    "B": (0.63, 0.78, 0.05, 0.20, 0.4, 0.04),
    "C": (0.31, 0.72, 0.08, 0.55, 0.4, 0.13),
    "D": (0.60, 0.73, 0.06, 0.18, 0.4, 0.05),
    "E": (0.55, 0.78, 0.05, 0.69, 0.5, 0.06),
    "F": (0.88, 0.80, 0.21, 0.10, 0.4, 0.05),
    "G": (0.48, 0.76, 0.06, 0.18, 0.98, 0.05),
    "H": (0.48, 0.84, 0.08, 0.26, 0.8, 0.05),
    "I": (0.57, 0.60, 0.08, 0.14, 0.4, 0.09),
    "J": (0.54, 0.96, 0.07, 0.22, 0.05, 0.04),
}
SETTINGS = {
    "base": (0.075, 0.003),
    "slow_fastforget": (0.035, 0.008),
    "fast_slowforget": (0.120, 0.001),
    "low_attendance": (0.075, 0.003),
}
DAYS = (7, 30, 90)


def experiment(spec):
    profile, seed, setting = spec
    initial, attend, slip, help_rate, memory, quit_rate = PROFILES[profile]
    gain, forget = SETTINGS[setting]
    if setting == "low_attendance":
        attend *= 0.55
    # Pair exogenous random draws by profile, seed, day, slot and skill across policies.
    gen = random.Random(901003 + seed * 104729 + ord(profile) * 1009)
    start = [min(0.98, max(0.08, initial + gen.uniform(-0.24, 0.24))) for _ in range(8)]
    days = [
        (gen.random(), [[gen.random() for _ in range(14)] for _ in range(5)]) for _ in range(90)
    ]
    rows = []
    for policy in POLICIES:
        engine = Engine(policy)
        truth = list(start)
        c = Counter()
        gap_days, award_days = [], []
        first_gap = {}
        seen_gap = set()
        family_seen = set()
        last_items = {}
        pending_help = set()
        for d, (arrive, slots) in enumerate(days, 1):
            truth = [max(0.08, v - forget * max(0.0, v - 0.12)) for v in truth]
            for k, v in enumerate(truth):
                if v < 0.55:
                    first_gap.setdefault(k, d)
            active = arrive < attend
            if profile == "D" and 6 <= (d - 1) % 21 < 18:
                active = False
            # Exam sprint starts now; after 14 days no further sessions.
            if profile == "J" and d > 14:
                active = False
            if active:
                c["sessions"] += 1
                chosen = engine.queue(d)
                if profile == "H":
                    # Learner often overrides the proposed list by requesting one easy skill.
                    chosen = [0 if r[10] < 0.72 else k for k, r in zip(chosen, slots, strict=False)]
                offered = 0
                for j, (k, r) in enumerate(zip(chosen, slots, strict=False)):
                    s = engine.skills[k]
                    if j and r[0] < quit_rate + (0.08 if s.stage == "practice" else 0):
                        break
                    offered += 1
                    c["offers"] += 1
                    family = int(r[1] * 3)
                    item = f"{k}-{family}-{int(r[2] * 120)}"
                    replay = k in last_items and r[3] < (
                        0.78 if profile == "G" else 0.76 if profile == "H" else 0.08
                    )
                    if replay:
                        item, family = last_items[k]
                    familiar = item in s.seen
                    diff = (family - 1) * 0.09
                    independent = max(0.02, min(0.98, truth[k] - diff)) * (1 - slip)
                    guess = 0.25 if k == 7 else 0.025
                    correct = r[4] < independent or r[5] < guess
                    if familiar and r[6] < memory:
                        correct = True
                    if r[7] < 0.025:
                        outcome = "skip"
                    elif r[8] < help_rate * (1.25 if not correct else 0.55):
                        outcome = "solution" if r[9] < 0.3 else "hint"
                    elif profile == "H" and r[12] < 0.20:
                        outcome = "error"
                    else:
                        outcome = "clean" if correct else "error"
                    if familiar:
                        c["familiar"] += 1
                    else:
                        c["new"] += 1
                        if outcome in ("clean", "error"):
                            if k in pending_help:
                                c["transfer_after_help_n"] += 1
                                c["transfer_after_help_yes"] += outcome == "clean"
                                pending_help.remove(k)
                            c["unaided"] += 1
                            c["new_correct"] += outcome == "clean"
                    if outcome in ("hint", "solution"):
                        c["assisted"] += 1
                        pending_help.add(k)
                    if outcome == "hint":
                        c["hint_success"] += r[13] < min(0.98, independent + 0.32)
                    if (
                        not familiar
                        and outcome in ("clean", "error")
                        and s.due is not None
                        and d >= s.due
                    ):
                        c["retention_n"] += 1
                        c["retention_yes"] += outcome == "clean"
                    prev_stage = s.stage
                    event = Event(f"{d}.{j}", d, k, item, family, outcome)
                    engine.apply(event)
                    if s.stage == "practice" and prev_stage != "practice":
                        c["gaps"] += 1
                        c["true_gap"] += truth[k] < 0.55
                        if truth[k] < 0.55 and k not in seen_gap:
                            gap_days.append(d - first_gap[k])
                            seen_gap.add(k)
                    if s.stage == "confirmed" and prev_stage != "confirmed":
                        c["closed"] += 1
                        c["false_close"] += truth[k] < 0.75
                        award_days.append(d)
                    last_items[k] = (item, family)
                    family_seen.add((k, family))
                    efficacy = {
                        "clean": 0.75,
                        "error": 0.42,
                        "hint": 1.0,
                        "solution": 0.55,
                        "skip": 0.0,
                    }[outcome]
                    truth[k] += gain * (1 - truth[k]) * efficacy * (0.27 if familiar else 1.0)
                    # Minutes are scenario assumptions including help overhead.
                    c["seconds"] += (35 + 65 * r[11]) * (
                        1.4 if outcome in ("hint", "solution") else 1.0
                    )
                c["complete"] += offered == 5
            if d in DAYS:
                # Fixed unseen transfer probes, no practice and no feedback. Every
                # skill is tested after seven modelled days without further study.
                probe = random.Random(104729 * seed + 97 * ord(profile) + d)
                responses = [
                    probe.random()
                    < (
                        max(0.02, v * (1 - forget) ** 7 - 0.09) * (1 - slip)
                        + (1 - max(0.02, v * (1 - forget) ** 7 - 0.09) * (1 - slip))
                        * (0.25 if k == 7 else 0.025)
                    )
                    for k, v in enumerate(truth)
                ]
                checked = [k for k, s in engine.skills.items() if s.stage == "confirmed"]
                rows.append(
                    dict(
                        profile=profile,
                        seed=seed,
                        setting=setting,
                        policy=policy,
                        probe_yes=sum(responses),
                        probe_n=len(responses),
                        probe_confirmed_yes=sum(responses[k] for k in checked),
                        probe_confirmed_n=len(checked),
                        day=d,
                        mastered=sum(v >= 0.75 for v in truth),
                        latent_mean=sum(truth) / 8,
                        award=len(engine.awards),
                        weak_truth=len(first_gap),
                        weak_found=len(seen_gap),
                        latency_gap_sum=sum(gap_days),
                        latency_gap_n=len(gap_days),
                        latency_award_sum=sum(award_days),
                        latency_award_n=len(award_days),
                        distinct_families=len(family_seen),
                        due=sum(s.due is not None and s.due <= d for s in engine.skills.values()),
                        **{key: c[key] for key in METRIC_COUNTS},
                    )
                )
    return rows


METRIC_COUNTS = (
    "sessions",
    "offers",
    "new",
    "complete",
    "familiar",
    "new_correct",
    "unaided",
    "retention_yes",
    "retention_n",
    "assisted",
    "hint_success",
    "gaps",
    "true_gap",
    "closed",
    "false_close",
    "seconds",
    "transfer_after_help_n",
    "transfer_after_help_yes",
)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--seeds", type=int, default=100)
    cli.add_argument("--workers", type=int, default=4)
    cli.add_argument("--output", type=Path, default=HERE / "results")
    args = cli.parse_args()
    if args.seeds < 1 or args.workers < 1:
        cli.error("positive seeds and workers required")
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = ((p, s, c) for c in SETTINGS for p in PROFILES for s in range(args.seeds))
    started = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        with (args.output / "runs.csv").open("w", newline="", encoding="utf8") as fh:
            writer = None
            for batch in pool.map(experiment, jobs, chunksize=8):
                if writer is None:
                    writer = csv.DictWriter(fh, fieldnames=batch[0])
                    writer.writeheader()
                writer.writerows(batch)
    print(
        json.dumps(
            {
                "runs": len(PROFILES) * args.seeds * len(SETTINGS) * 3,
                "seconds": round(perf_counter() - started, 1),
                "seeds": args.seeds,
            }
        )
    )


if __name__ == "__main__":
    main()
