#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
backup_name="shuttleup-$(date -u +%Y%m%dT%H%M%SZ)-$$.db"
docker compose exec -T app shuttleup backup "/data/backups/$backup_name"
docker compose cp "app:/data/backups/$backup_name" "backups/$backup_name"
chmod 600 "backups/$backup_name"
printf '备份已保存：backups/%s\n' "$backup_name"
