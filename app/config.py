from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    webhook_base_url: str | None = None
    log_level: str = "INFO"
    oge15_pilot_enabled: bool = False
    oge15_pilot_user_ids: str = ""

    @property
    def oge15_pilot_users(self) -> frozenset[int]:
        """Parse an explicit comma-separated Telegram ID allowlist fail-closed."""
        values: set[int] = set()
        for value in self.oge15_pilot_user_ids.split(","):
            value = value.strip()
            if not value:
                continue
            if not value.isascii() or not value.isdigit() or int(value) <= 0:
                return frozenset()
            values.add(int(value))
        return frozenset(values)

    def can_use_oge15_pilot(self, telegram_user_id: int | None) -> bool:
        return bool(
            self.oge15_pilot_enabled
            and telegram_user_id is not None
            and telegram_user_id in self.oge15_pilot_users
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
