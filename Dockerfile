# syntax=docker/dockerfile:1.7
FROM node:24-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS pybuilder
ARG SQLITE_VERSION=3510300
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://www.sqlite.org/2026/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" -o /tmp/sqlite.tar.gz \
 && mkdir /tmp/sqlite-src \
 && tar -xzf /tmp/sqlite.tar.gz -C /tmp/sqlite-src --strip-components=1 \
 && cd /tmp/sqlite-src \
 && ./configure --prefix=/usr/local --disable-static \
 && make -j2 \
 && make install \
 && ldconfig \
 && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version"
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --locked --no-dev

FROM python:3.12-slim-bookworm
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 LD_LIBRARY_PATH=/usr/local/lib
RUN useradd --create-home --uid 10001 shuttleup && mkdir -p /data /app && chown -R shuttleup:shuttleup /data /app
COPY --from=pybuilder /usr/local/lib/libsqlite3.so* /usr/local/lib/
RUN ldconfig && python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version"
WORKDIR /app
COPY --from=pybuilder --chown=shuttleup:shuttleup /app/.venv ./.venv
COPY --chown=shuttleup:shuttleup pyproject.toml uv.lock ./
COPY --chown=shuttleup:shuttleup backend/ ./backend/
COPY --from=web --chown=shuttleup:shuttleup /src/backend/shuttleup/static ./backend/shuttleup/static
COPY --chown=shuttleup:shuttleup scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh
USER shuttleup
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

