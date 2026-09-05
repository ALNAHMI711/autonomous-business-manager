from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------
    # Application
    # ------------------------------------------------------------

    app_name: str = "Autonomous Business Manager"
    app_env: str = "development"
    debug: bool = False

    # ------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------

    admin_password: str = Field(
        default="",
        repr=False,
    )

    api_panel_password: str = Field(
        default="",
        repr=False,
    )

    session_secret: str = Field(
        default="change-this-session-secret",
        repr=False,
    )

    encryption_key: str = Field(
        default="",
        repr=False,
    )

    # ------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------

    openai_api_key: Optional[str] = Field(
        default=None,
        repr=False,
    )

    openai_model: str = "gpt-5.6"

    # ------------------------------------------------------------
    # Database / Storage
    # ------------------------------------------------------------

    database_path: str = str(
        BASE_DIR / "data" / "business_manager.db"
    )

    upload_dir: str = str(
        BASE_DIR / "uploads"
    )

    browser_profile_dir: str = str(
        BASE_DIR / "browser_profiles"
    )

    max_upload_size: int = 10 * 1024 * 1024

    # ------------------------------------------------------------
    # Browser
    # ------------------------------------------------------------

    browser_headless: bool = True

    browser_timeout: int = 30000

    # ------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------

    connectivity_check_url: str = (
        "https://www.google.com/generate_204"
    )

    connectivity_interval: int = 15

    # ------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------

    telegram_bot_token: Optional[str] = Field(
        default=None,
        repr=False,
    )

    telegram_chat_id: Optional[str] = Field(
        default=None,
        repr=False,
    )

    # ------------------------------------------------------------
    # WhatsApp Business API
    # ------------------------------------------------------------

    whatsapp_api_url: Optional[str] = None

    whatsapp_access_token: Optional[str] = Field(
        default=None,
        repr=False,
    )

    whatsapp_phone_number_id: Optional[str] = None

    whatsapp_recipient: Optional[str] = None

    # ------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------

    timezone: str = "UTC"

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path)

        if not path.is_absolute():
            path = BASE_DIR / path

        return path

    @property
    def upload_directory(self) -> Path:
        path = Path(self.upload_dir)

        if not path.is_absolute():
            path = BASE_DIR / path

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    @property
    def browser_profile_directory(self) -> Path:
        path = Path(self.browser_profile_dir)

        if not path.is_absolute():
            path = BASE_DIR / path

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    def ensure_directories(self) -> None:
        self.database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.upload_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.browser_profile_directory.mkdir(
            parents=True,
            exist_ok=True,
        )


settings = Settings()

settings.ensure_directories()
