from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    wakeup_share_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
