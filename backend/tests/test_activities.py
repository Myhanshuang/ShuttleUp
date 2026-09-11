import httpx
import pytest

pytestmark = pytest.mark.asyncio

async def guest(client, name):
    response = await client.post("/api/v1/auth/guest", json={"display_name": name})
    return response.json()["csrf_token"]


async def test_create_invite_join_is_idempotent(client):
    csrf = await guest(client, "主持人")
    created = await client.post("/api/v1/activities", headers={"X-CSRF-Token": csrf}, json={"title": "周末打球"})
    assert created.status_code == 201
    token = created.json()["invite_token"]
    assert (await client.get(f"/api/v1/invites/{token}")).json()["participant_count"] == 1

    other = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    async with other:
        joined = await other.post(f"/api/v1/invites/{token}/join", json={"display_name": "成员"})
        assert joined.status_code == 200
        joined2 = await other.post(f"/api/v1/invites/{token}/join", json={})
        assert joined2.status_code == 200
        assert (await other.get(f"/api/v1/activities/{created.json()['id']}")).json()["participant_count"] == 2


async def test_member_cannot_patch_activity(client):
    csrf = await guest(client, "主持人")
    created = (await client.post("/api/v1/activities", headers={"X-CSRF-Token": csrf}, json={"title": "周末打球"})).json()
    token = created["invite_token"]
    other = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")
    async with other:
        joined = (await other.post(f"/api/v1/invites/{token}/join", json={"display_name": "成员"})).json()
        result = await other.patch(f"/api/v1/activities/{created['id']}", headers={"X-CSRF-Token": joined["csrf_token"]}, json={"title": "越权", "expected_version": 2})
        assert result.status_code == 403
