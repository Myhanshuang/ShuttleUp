"""Read a backup from stdin. Run only with the app stopped; retain replaced files."""
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

root = Path("/data")
descriptor, name = tempfile.mkstemp(prefix="restore-", suffix=".db", dir=root)
temporary = Path(name)
try:
    with os.fdopen(descriptor, "wb") as stream:
        shutil.copyfileobj(sys.stdin.buffer, stream)
    with sqlite3.connect(f"file:{temporary}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("备份完整性检查失败")
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
            raise RuntimeError("不是 ShuttleUp 数据库")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for suffix in ("", "-wal", "-shm"):
        old = root / ("shuttleup.db" + suffix)
        if old.exists(): old.rename(root / ("before-restore-" + stamp + ".db" + suffix))
    temporary.replace(root / "shuttleup.db")
    print("备份已导入，原数据库已保留。请检查迁移记录后再启动应用。")
finally:
    temporary.unlink(missing_ok=True)
