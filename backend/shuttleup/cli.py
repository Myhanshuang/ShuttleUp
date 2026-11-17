import argparse
import getpass
import sqlite3
from pathlib import Path

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import AppSetting, User
from .security import hash_password


def create_admin(args):
    username = (args.username or input("用户名: ")).lower()
    password = args.password or getpass.getpass("密码（至少 10 位）: ")
    display_name = args.display_name or input("显示昵称: ")
    if len(password) < 10:
        raise SystemExit("密码至少 10 位")
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("用户名已存在")
        db.add(User(username=username, password_hash=hash_password(password), display_name=display_name, is_admin=True))
        if not db.get(AppSetting, 1):
            db.add(AppSetting(id=1))
    print(f"管理员 {username} 已创建")


def backup(args):
    source_path = engine.url.database
    target = Path(args.path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    print(f"备份已写入 {target}")


def main():
    parser = argparse.ArgumentParser(prog="shuttleup")
    sub = parser.add_subparsers(required=True)
    admin = sub.add_parser("admin")
    admin_sub = admin.add_subparsers(required=True)
    create = admin_sub.add_parser("create")
    create.add_argument("--username"); create.add_argument("--password"); create.add_argument("--display-name")
    create.set_defaults(func=create_admin)
    b = sub.add_parser("backup"); b.add_argument("path"); b.set_defaults(func=backup)
    from .venues.local import extensions
    for extension in extensions():
        if hasattr(extension, "register_cli"):
            extension.register_cli(sub)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__":
    main()

