import httpx
import pytest
from sqlalchemy import select
from shuttleup.auth import email as mail, password_reset as reset
from shuttleup.models import PasswordResetChallenge, User

pytestmark = pytest.mark.asyncio

@pytest.fixture
def outbox(monkeypatch):
    settings = mail.get_settings().model_copy(update={"smtp_host":"smtp.example.com", "smtp_from":"sender@example.com"})
    monkeypatch.setattr(mail, "get_settings", lambda: settings)
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda address, code: sent.append(("register", address, code)))
    monkeypatch.setattr(reset, "send_reset_code", lambda address, code: sent.append(("reset", address, code)))
    return sent

async def register(client, outbox):
    issued = (await client.post("/api/v1/auth/email/code", json={"email":"player@example.com"})).json()
    body = {"email":"player@example.com", "challenge_id":issued["challenge_id"], "code":outbox[-1][2], "password":"original-password", "display_name":"原有球友"}
    result = (await client.post("/api/v1/auth/email/register", json=body)).json()
    return result, body

async def request_reset(client, outbox):
    issued = await client.post("/api/v1/auth/password/code", json={"email":"PLAYER@example.com"})
    assert issued.status_code == 202, issued.text
    return {"email":"player@example.com", "challenge_id":issued.json()["challenge_id"], "code":outbox[-1][2], "password":"replacement-password"}

async def test_reset_preserves_identity_revokes_all_sessions_and_cannot_replay(client, outbox):
    identity, registration = await register(client, outbox)
    csrf = {"X-CSRF-Token":identity["csrf_token"]}
    activity = (await client.post("/api/v1/activities", headers=csrf, json={"title":"保留的活动"})).json()
    async with httpx.AsyncClient(transport=client._transport, base_url="http://testserver") as other:
        await other.post("/api/v1/auth/login", json={"username":registration["email"],"password":registration["password"]})
        client.cookies.clear()
        body = await request_reset(client, outbox)
        assert (await client.post("/api/v1/auth/password/reset",json=registration)).status_code==422
        result = await client.post("/api/v1/auth/password/reset",json=body)
        assert result.status_code==200 and result.headers["cache-control"]=="no-store"
        assert (await other.get("/api/v1/session")).json()["user"] is None
        assert (await client.post("/api/v1/auth/password/reset",json=body)).status_code==422
        assert (await client.post("/api/v1/auth/login",json={"username":body["email"],"password":registration["password"]})).status_code==401
        logged=(await client.post("/api/v1/auth/login",json={"username":body["email"],"password":body["password"]})).json()
        assert logged["user"]["id"]==identity["user"]["id"]
        assert (await client.get(f"/api/v1/activities/{activity['id']}")).status_code==200

async def test_reset_guess_expiration_resend_and_privacy(client, outbox):
    await register(client,outbox); client.cookies.clear()
    body=await request_reset(client,outbox)
    assert (await client.post("/api/v1/auth/password/code",json={"email":body["email"]})).status_code==429
    wrong="000000" if body["code"]!="000000" else "111111"
    for _ in range(5):
        assert (await client.post("/api/v1/auth/password/reset",json={**body,"code":wrong})).status_code==422
    assert (await client.post("/api/v1/auth/password/reset",json=body)).status_code==422
    with client.testing_session_factory.begin() as db:
        db.get(PasswordResetChallenge,body["challenge_id"]).sent_at=0
    replaced=await request_reset(client,outbox)
    assert (await client.post("/api/v1/auth/password/reset",json=body)).status_code==422
    with client.testing_session_factory.begin() as db:
        db.get(PasswordResetChallenge,replaced["challenge_id"]).expires_at=0
    assert (await client.post("/api/v1/auth/password/reset",json=replaced)).status_code==422
    count=len(outbox)
    absent=await client.post("/api/v1/auth/password/code",json={"email":"absent@example.com"})
    assert absent.status_code==202 and "user" not in absent.json() and len(outbox)==count
    with client.testing_session_factory.begin() as db:
        user=db.scalar(select(User)); user.disabled_at=1
        db.get(PasswordResetChallenge,replaced["challenge_id"]).sent_at=0
    disabled=await client.post("/api/v1/auth/password/code",json={"email":"player@example.com"})
    assert disabled.status_code==202 and len(outbox)==count
    assert disabled.json().keys()==absent.json().keys()

async def test_failed_mail_and_csrf_do_not_reset_password(client,outbox,monkeypatch):
    identity, _ = await register(client,outbox)
    assert (await client.post("/api/v1/auth/password/code",json={"email":"player@example.com"})).status_code==403
    client.cookies.clear()
    def broken(*args): raise RuntimeError("private SMTP credential")
    monkeypatch.setattr(reset,"send_reset_code",broken)
    result=await client.post("/api/v1/auth/password/code",json={"email":"player@example.com"})
    assert result.status_code==503 and "private" not in result.text
    with client.testing_session_factory() as db:
        assert db.get(User,identity["user"]["id"]).password_hash
