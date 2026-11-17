"""Fail clearly before starting a production container with unsafe placeholders."""
import os
import sys
from sqlalchemy import inspect
from shuttleup.config import get_settings
from shuttleup.db import engine

settings = get_settings()
for name, value in [("APP_SECRET", settings.app_secret), ("ASTRBOT_MAIN_TOKEN", settings.astrbot_main_token)]:
    if len(value) < 32 or value.startswith(("development-", "replace-")):
        sys.exit(f"请在 .env 中为 {name} 设置至少 32 位随机密钥。")
if not settings.app_base_url.startswith(("https://", "http://")):
    sys.exit("APP_BASE_URL 必须是完整的 http(s) 地址。")
if settings.app_base_url.startswith("https://") and not settings.session_cookie_secure:
    sys.exit("HTTPS 部署必须设置 SESSION_COOKIE_SECURE=true。")
tables = set(inspect(engine).get_table_names())
if tables and "alembic_version" not in tables:
    sys.exit("数据库没有迁移记录。请按 docs/deployment.md 的现有数据迁移步骤导入；不要直接执行 stamp head。")
