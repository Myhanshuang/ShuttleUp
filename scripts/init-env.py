"""Create a new deployment .env without overwriting an existing configuration."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
template = (root / ".env.example").read_text()
template = template.replace("replace-with-at-least-32-random-characters", secrets.token_hex(32))
template = template.replace("replace-with-a-random-service-token", secrets.token_hex(32))
try:
    descriptor = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env 已存在，未修改。请编辑现有配置。")
with os.fdopen(descriptor, "w") as stream:
    stream.write(template)
print("已创建 .env 并生成随机密钥。请填写域名、SMTP 和管理员邮箱；密钥不会显示在终端。")
