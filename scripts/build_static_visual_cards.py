"""Build the bot's static PNGs from the same catalogues used by its keyboards."""

import argparse
import sys
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from app.bot import adaptive, menu, scenario_training  # noqa: E402
from app.bot.progress import _numbers_card  # noqa: E402
from app.bot.visual_cards import render_card  # noqa: E402
from app.bot.visual_models import VisualCard  # noqa: E402
from app.bot.visual_static import STATIC_DIRECTORY, static_path  # noqa: E402
from app.config import Settings, test_settings  # noqa: E402


def static_cards() -> Iterator[VisualCard]:
    for written in (False, True):
        token = test_settings.set(Settings(_env_file=None, oge_part2_enabled=written))
        try:
            yield menu.welcome_card()
            yield _numbers_card()
            if written:
                yield menu.number_card(
                    include_task7=True, include_task11=True, include_task13=True,
                )[0]
                yield menu.number_card(page=99)[0]
        finally:
            test_settings.reset(token)

    yield _numbers_card(journal_origin="history:0")
    yield _numbers_card(journal_origin="errors:0")
    yield scenario_training.story_card()
    yield scenario_training.story_card(linked_only=True)
    catalog = adaptive.catalog()
    for number in range(1, 6):
        yield scenario_training.story_card(number)
        yield adaptive.picker_card(number)
        for story, families in adaptive.story_families(number).items():
            if len(families) > 1:
                yield adaptive.picker_card(number, story=story)
    for number in sorted(set(catalog.values()) - set(range(1, 6))):
        count = sum(n == number for n in catalog.values())
        for page in range((count + 4) // 5):
            yield adaptive.picker_card(number, page)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the packaged catalogue")
    check = parser.parse_args().check
    cards = {static_path(card): card for card in static_cards()}
    actual = set(STATIC_DIRECTORY.glob("*.png"))
    if check:
        if actual != cards.keys():
            missing, obsolete = cards.keys() - actual, actual - cards.keys()
            raise SystemExit(f"Missing: {sorted(missing)}\nObsolete: {sorted(obsolete)}")
        seen = {}
        for path, card in cards.items():
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise SystemExit(f"Expected PNG: {path}")
                image.verify()
            if card.screen in {"welcome", "progress_numbers"}:
                with Image.open(path) as image:
                    key = (image.size, sha256(image.convert("RGBA").tobytes()).digest())
                if key in seen:
                    raise SystemExit(f"Duplicate artwork: {seen[key]} and {path}")
                seen[key] = path
    else:
        STATIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
        for path, card in cards.items():
            path.write_bytes(render_card(card))
        for path in actual - cards.keys():
            path.unlink()
    print(f"{len(cards)} static PNG cards")


if __name__ == "__main__":
    main()
