from contextvars import ContextVar
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GRADING_MODEL = "gpt-6.1-terra"
GRADING_REASONING: Literal["low"] = "low"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str | None = None
    telegram_bot_token: str | None = None
    # Optional companion settings are validated only in its background startup.
    telegram_test_bot_token: SecretStr | None = None
    telegram_test_owner_ids: str = ""
    telegram_webhook_secret: str | None = None
    webhook_base_url: str | None = None
    oge_adaptive_enabled: bool = False
    oge_adaptive_capture_only: bool = False
    oge_companion_adaptive_capture_only: bool = False
    oge_companion_adaptive_enabled: bool = False
    oge_part2_enabled: bool = False
    oge_visual_welcome_enabled: bool = False
    oge_visual_numbers_enabled: bool = False
    oge_visual_part2_enabled: bool = False
    oge_visual_stories_enabled: bool = False
    oge_visual_types_enabled: bool = False
    oge_visual_number_progress_enabled: bool = False
    oge_visual_training_result_enabled: bool = False
    oge_visual_companion_only: bool = False
    # Empty means all users in this environment for the explicitly enabled screens.
    oge_visual_user_ids: str = ""
    oge_grading_max_images: int = Field(default=1, ge=1, le=1)
    oge_grading_enabled: bool = False
    oge_grading_model: str = GRADING_MODEL
    openai_api_key: SecretStr | None = None
    oge_grading_daily_user_limit: int = Field(default=25, ge=0, le=25)
    oge_grading_monthly_user_limit: int = Field(default=150, ge=0, le=150)
    oge_grading_monthly_budget_usd: Decimal = Field(default=Decimal(5), ge=0, le=5)
    oge_grading_timeout_seconds: int = Field(default=45, ge=1, le=120)
    oge_grading_context_tokens: int = Field(default=30000, ge=1, le=30000)
    oge_grading_request_budget_usd: Decimal = Field(
        default=Decimal("0.10"), ge=0, le=Decimal("0.10")
    )
    log_level: str = "INFO"


test_settings: ContextVar[Settings | None] = ContextVar("test_settings", default=None)


@lru_cache
def _default_settings() -> Settings:
    return Settings()


class SettingsProvider:
    def __call__(self) -> Settings:
        return test_settings.get() or _default_settings()

    def cache_clear(self) -> None:
        _default_settings.cache_clear()


get_settings = SettingsProvider()
