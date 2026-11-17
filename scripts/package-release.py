"""Package deployment sources using an allowlist; never include local data/secrets."""
from pathlib import Path
import hashlib
import tarfile

root = Path(__file__).resolve().parents[1]
out = root / "release"
out.mkdir(exist_ok=True)
archive = out / "shuttleup-server.tar.gz"
allowed = ["Dockerfile", "compose.yaml", "compose.https.yaml", ".dockerignore", ".gitignore", ".env.example", "pyproject.toml", "uv.lock", "README.md", "backend/alembic.ini"]
directories = ["backend/shuttleup", "backend/migrations", "frontend/src", "frontend/public", "scripts", "deploy", "docs", "plugins/astrbot_plugin_shuttleup"]
files = [root / name for name in allowed]
files += [p for p in (root / "frontend").iterdir() if p.is_file() and p.suffix in (".json", ".html", ".ts")]
for name in directories:
    files += [p for p in (root / name).rglob("*") if p.is_file()]
def safe(p):
    relative = p.relative_to(root)
    return not p.is_symlink() and not any(part in {"__pycache__", ".pytest_cache", "static", "extensions", "node_modules", ".local"} for part in relative.parts) and not p.name.startswith(".env") and p.suffix not in {".pyc", ".db"}
with tarfile.open(archive, "w:gz") as tar:
    for p in sorted(set(files)):
        if safe(p) or p == root / ".env.example":
            tar.add(p, arcname=str(Path("shuttleup") / p.relative_to(root)), recursive=False)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(out / "shuttleup-server.tar.gz.sha256").write_text(f"{checksum}  {archive.name}\n")
print(f"已生成 {archive}（不含 .env、数据库、私有扩展或本机依赖）")
