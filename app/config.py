from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Autonomous Business Manager"
    app_env: str = "production"
    debug: bool = False

    admin_password: str
    api_panel_password: str

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6"

    database_path: str = str(BASE_DIR / "data" / "business_manager.db")
    upload_dir: str = str(BASE_DIR / "data" / "uploads")

    session_secret: str
    encryption_key: str

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    whatsapp_enabled: bool = False
    whatsapp_api_url: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_recipient: str | None = None

    browser_headless: bool = True
    browser_timeout_ms: int = 30000

    max_upload_mb: int = 25

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        Path(self.database_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        Path(self.upload_dir).mkdir(
            parents=True,
            exist_ok=True,
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
