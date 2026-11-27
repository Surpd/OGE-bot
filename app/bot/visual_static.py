"""Resolve packaged artwork against the exact on-screen copy and catalogue."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from app.bot.visual_models import VisualCard

STATIC_DIRECTORY = Path(__file__).with_name("visual_assets") / "static"
STATIC_SCREENS = frozenset({"welcome", "numbers", "part2", "stories", "types", "progress_numbers"})


def is_static(card: VisualCard) -> bool:
    return card.screen in STATIC_SCREENS and not card.personalized


def static_path(card: VisualCard) -> Path:
    content = json.dumps(asdict(card), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256(content.encode("utf-8")).hexdigest()[:20]
    return STATIC_DIRECTORY / f"{card.screen.replace('_', '-')}-{fingerprint}.png"
