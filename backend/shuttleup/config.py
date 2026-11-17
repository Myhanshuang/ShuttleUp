from functools import lru_cache
from pathlib import Path

from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_base_url: str = "http://localhost:8000"
    app_timezone: str = "Asia/Shanghai"
    app_secret: str = Field(default="development-secret-change-me", min_length=16)
    database_url: str = "sqlite:///./data/shuttleup.db"
    session_cookie_secure: bool = False
    astrbot_main_token: str = "development-bot-token"
    log_level: str = "INFO"
    static_dir: Path = Path(__file__).parent / "static"
    demo_mode: bool = False
    bootstrap_admin_email: EmailStr | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_security: str = Field(default="starttls", pattern="^(starttls|ssl)$")
    wakeup_share_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
