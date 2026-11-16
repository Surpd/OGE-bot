"""Opt-in adapter factory only; does not register routes, menu, callbacks or DB methods."""

from app.bot.training_engine import NumericTraining
from app.math.oge16_circles import POLICY
from app.math.oge16_scheduler import build_task16_candidate_batch


def numeric_training_adapter() -> NumericTraining:
    """Future integration must add task16 persistence and saved-figure presentation first."""
    return NumericTraining(16, "окружности", POLICY, build_task16_candidate_batch)
