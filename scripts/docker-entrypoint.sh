#!/bin/sh
set -eu
alembic -c backend/alembic.ini upgrade head
exec uvicorn shuttleup.app:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"

