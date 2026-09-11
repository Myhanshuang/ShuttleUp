import pytest

pytestmark = pytest.mark.asyncio

async def test_guest_session_and_upgrade_keeps_identity(client):
    guest = await client.post("/api/v1/auth/guest", json={"display_name": "小林"})
    assert guest.status_code == 201
    user_id = guest.json()["user"]["id"]
    upgraded = await client.post("/api/v1/auth/register", json={"username": "lin_01", "password": "long-enough-password"})
    assert upgraded.status_code == 201
    assert upgraded.json()["user"]["id"] == user_id
    assert (await client.get("/api/v1/session")).json()["user"]["username"] == "lin_01"


async def test_login_rejects_wrong_password(client):
    await client.post("/api/v1/auth/register", json={"username": "player", "password": "long-enough-password"})
    assert (await client.post("/api/v1/auth/login", json={"username": "player", "password": "wrong-password"})).status_code == 401
