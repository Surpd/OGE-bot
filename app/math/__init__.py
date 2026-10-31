"""Platform-independent exact arithmetic generators for OGE Trainer."""

from app.math.generator import (
    GENERATOR_VERSION,
    SUPPORTED_FAMILIES,
    choose_family,
    generate,
    generate_random,
)
from app.math.problem import Problem

__all__ = [
    "GENERATOR_VERSION",
    "SUPPORTED_FAMILIES",
    "Problem",
    "choose_family",
    "generate",
    "generate_random",
]
