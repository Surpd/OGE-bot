"""Adversarial exposure: a student who knows no answers guesses one fresh item daily."""

import csv
import random
from pathlib import Path

from model import Engine, Event


def evaluate(policy, chance, days=90, runs=1000):
    fooled = 0
    for seed in range(runs):
        rng = random.Random(seed)
        engine = Engine(policy, (0,))
        for day in range(days):
            outcome = "clean" if rng.random() < chance else "error"
            engine.apply(Event(str(day), day, 0, str(day), day % 2, outcome))
        fooled += int(bool(engine.awards))
    return fooled


if __name__ == "__main__":
    with Path(__file__).with_name("guessing.csv").open("w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("policy", "guess_probability", "days", "seeds", "ever_awarded"))
        for policy in ("rules", "weighted", "bkt"):
            for chance in (0.05, 1 / 3, 0.5):
                value = evaluate(policy, chance)
                writer.writerow((policy, chance, 90, 1000, value))
                print(policy, round(chance, 3), value)
