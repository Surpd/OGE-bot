from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    webhook_base_url: str | None = None
    oge_part2_enabled: bool = False
    oge_grading_max_images: int = Field(default=4, ge=1, le=8)
    oge_grading_enabled: bool = False
    oge_grading_model: str = "gpt-6.2-sol"
    openai_api_key: SecretStr | None = None
    oge_grading_daily_user_limit: int = Field(default=4, ge=0)
    oge_grading_monthly_budget_usd: Decimal = Field(default=Decimal(0), ge=0)
    oge_grading_timeout_seconds: int = Field(default=45, ge=1, le=120)
    # Verified tariff and context ceiling for this exact model before first paid use.
    oge_grading_tariff_model: str = ""
    oge_grading_input_usd_per_million: Decimal = Field(default=Decimal(0), ge=0)
    oge_grading_output_usd_per_million: Decimal = Field(default=Decimal(0), ge=0)
    oge_grading_context_tokens: int = Field(default=0, ge=0)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
