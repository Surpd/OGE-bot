"""Shuffled number cycles for mixed first-part practice."""

from random import Random
from typing import Any


def reserve_number(
    rotation: dict[str, Any], available: set[int], batch: list[int],
) -> tuple[int, dict[str, Any]]:
    """Choose the next number and return the state to commit on delivery."""
    previous = set(rotation.get("available", ()))
    remaining = [number for number in rotation.get("remaining", ()) if number in available]
    index = rotation.get("index", -1)
    additions = sorted(available - previous)
    if remaining and additions:
        Random(f"{rotation['seed']}:{index}:added").shuffle(additions)
        remaining.extend(additions)
    if not remaining:
        index += 1
        remaining = sorted(available)
        Random(f"{rotation['seed']}:{index}").shuffle(remaining)
    number = next((value for value in remaining if value not in batch), remaining[0])
    return number, {
        "seed": rotation["seed"],
        "available": sorted(available),
        "index": index,
        "remaining": [value for value in remaining if value != number],
    }


def preview_plan(catalog: dict[str, int], rotation: dict[str, Any], size: int) -> list[str]:
    first_families = {number: family for family, number in sorted(catalog.items(), reverse=True)}
    batch: list[int] = []
    for _ in range(size):
        number, rotation = reserve_number(rotation, set(first_families), batch)
        batch.append(number)
    return [first_families[number] for number in batch]
