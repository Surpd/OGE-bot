"""NumericTraining adapter for the ordinary №16 Telegram training flow."""

from app.bot.training_engine import NumericTraining
from app.math.oge16_circles import POLICY
from app.math.oge16_scheduler import build_task16_candidate_batch


def numeric_training_adapter() -> NumericTraining:
    """Return the registered adapter; public availability follows the scheduler gate."""
    return NumericTraining(16, "окружности", POLICY, build_task16_candidate_batch)
