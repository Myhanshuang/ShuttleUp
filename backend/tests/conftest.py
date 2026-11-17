import os
from pathlib import Path

import pytest_asyncio
import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from shuttleup.db import Base, get_db
from shuttleup.app import app


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON"); conn.execute("PRAGMA journal_mode=WAL")
    TestingSession = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    async def override_db():
        with TestingSession() as db: yield db
    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        c.testing_session_factory = TestingSession
        yield c
    app.dependency_overrides.clear()

async def join_times(client, token):
    summary = (await client.get(f'/api/v1/invites/{token}')).json()
    return [{'date': summary['date_from'], 'start': '08:00', 'end': '09:00'}]
