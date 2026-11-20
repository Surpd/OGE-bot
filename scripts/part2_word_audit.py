"""Reconstruct №21 answers from the published statement using exact equations."""

import json
import re
from pathlib import Path

from sympy import Q, Rational, ask, simplify, solve, symbols

from scripts.part2_algebra_audit import expression, formulas

ATLAS = Path(__file__).resolve().parents[1] / "atlas/part2/tasks.jsonl"
X = symbols("x", positive=True)


def root(equation, lower=0, upper=None):
    admissible = [
        r
        for r in solve(equation, X)
        if ask(Q.positive(r - lower)) and (upper is None or ask(Q.positive(upper - r)))
    ]
    if len(admissible) != 1:
        raise ValueError(f"Expected one physical solution, got {admissible} for {equation}")
    return admissible[0]


def expected(statement: str, subtype: str):
    values = [Rational(v.replace(",", ".")) for v in re.findall(r"\d+(?:[.,]\d+)?", statement)]
    if subtype == "mix-ratio":
        a, b, mixture = values
        if not min(a, b) < mixture < max(a, b):
            raise ValueError("Mixture must lie between component concentrations")
        return (b - mixture) / (mixture - a)
    if subtype == "mix-two-experiments":
        first, second, total, equal = values
        a = (total * (first + second) - 2 * equal * second) / (first - second)
        b = 2 * equal - a
        if not 0 <= a <= 100 or not 0 <= b <= 100:
            raise ValueError("Impossible concentration")
        return b * second / 100 if "втором сосуде" in statement else a * first / 100
    if subtype == "mass-invariant":
        fresh, dried, mass = values
        ratio = (100 - fresh) / (100 - dried)
        return mass / ratio if "Найдите массу свежих" in statement else mass * ratio
    if subtype == "finish-gap":
        distance, difference, earlier = values
        slow = root(distance / X - distance / (X + difference) - earlier)
        return slow + difference if "скорость первого" in statement else slow
    if subtype == "meeting-pause":
        if len(values) == 4:
            distance, first, second, pause_minutes = values
            return second * (distance + first * pause_minutes / 60) / (first + second)
        distance, difference, position = values
        from_a = "от A" in statement
        cyclist_a = "Из A в сторону B отправился велосипедист" in statement
        bicycle = position if from_a == cyclist_a else distance - position
        walking = distance - bicycle
        walker = root(walking / X - bicycle / (X + difference) - Rational(1, 2))
        return walker + difference if "скорость велосипедиста" in statement else walker
    if subtype == "meeting-arrivals":
        meeting, difference = (v / 60 for v in values)
        return root(meeting / (X - difference) + meeting / X - 1, difference)
    if subtype == "out-back-pause":
        if len(values) == 2 and "трёхчасовую" in statement:
            values.append(Rational(3))
        distance, gain, pause = values
        outward = root(distance / X - distance / (X + gain) - pause)
        return outward + gain if "скорость на пути из B" in statement else outward
    if subtype == "split-equal-time":
        if len(values) == 3:
            loss, speed, minimum = values
            return root(2 / X - 1 / (X - loss) - 1 / speed, max(minimum, loss))
        speed, gain = values
        return root(2 / X - 1 / speed - 1 / (X + gain))
    if subtype == "average-speed":
        if len(values) == 2:
            return 2 / sum(1 / v for v in values)
        portions = list(zip(values[::2], values[1::2], strict=True))
        if re.search(r"\d+ ч при", statement):
            return sum(t * speed for t, speed in portions) / sum(values[::2])
        return sum(values[::2]) / sum(distance / speed for distance, speed in portions)
    if subtype == "relative-motion":
        train, seconds, walker = values
        relative = train + walker if "навстречу" in statement else train - walker
        return relative * seconds * Rational(5, 18)
    if subtype == "loop":
        remaining, earlier, gain = values
        return root((1 - earlier / 60) * (X + gain) - (X + remaining))
    if subtype == "river-total":
        if "Найдите скорость течения" in statement:
            distance, pause, total, boat = values
            return root(distance / (boat + X) + distance / (boat - X) - (total - pause), upper=boat)
        down, up, total, *rest = values
        pause, current = (0, rest[0]) if len(rest) == 1 else rest
        return root(down / (X + current) + up / (X - current) - (total - pause), current)
    if subtype == "river-gap":
        distance, gain, current = values
        return root(distance / (X - current) - distance / (X + current) - gain, current)
    if subtype == "river-raft":
        delay, distance, raft_distance, current = values
        time = raft_distance / current - delay
        return root(distance / (X + current) + distance / (X - current) - time, current)
    if subtype == "rate-compare":
        if len(values) == 3:
            order, gain, earlier = values
            return root(order / X - order / (X + gain) - earlier)
        gain, fast_volume, earlier, slow_volume = values
        rate = root(slow_volume / X - fast_volume / (X + gain) - earlier)
        return rate if "через первую" in statement else rate + gain
    if subtype == "joint-sum":
        rates = [1 / t for t in values]
        total = sum(rates) / 2
        if min(total - rate for rate in rates) <= 0:
            raise ValueError("At least one worker rate is not positive")
        return (60 if "За сколько минут" in statement else 1) / total
    raise ValueError(f"Unrecognized subtype {subtype}")


def compare(card):
    (answer,) = formulas(card["answer_or_claim"])
    result = expected(card["statement"], card["subtype_id"].removeprefix("OGE21-"))
    published = expression(answer.replace(":", "/"))
    if simplify(result - published) != 0:
        raise ValueError(f"{card['task_id']}: statement gives {result}, atlas {published}")


if __name__ == "__main__":
    cards = [
        c for line in ATLAS.read_text().splitlines() if (c := json.loads(line))["number"] == 21
    ]
    for item in cards:
        compare(item)
    print(f"Verified exact answers from the statements for {len(cards)} word problems")
