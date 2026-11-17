"""Adopt a create_all database only when it exactly matches this release's schema."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from shuttleup.db import Base, engine
from shuttleup import models

if engine.dialect.name != "sqlite":
    raise SystemExit("此工具仅用于 SQLite。")
with engine.connect() as connection:
    if "alembic_version" in inspect(connection).get_table_names():
        raise SystemExit("已有迁移记录，请使用正常启动迁移流程。")
    differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    if differences:
        raise SystemExit("现有数据库结构与本版本不一致，未标记版本。请先在副本上升级，不能直接 stamp head。")
source = Path(engine.url.database)
backup = source.with_name(source.name + ".before-adopt-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(descriptor)
with sqlite3.connect(source) as original, sqlite3.connect(backup) as copy:
    original.backup(copy)
command.stamp(Config("backend/alembic.ini"), "head")
print("结构验证通过，已保留备份并补齐迁移记录。")
