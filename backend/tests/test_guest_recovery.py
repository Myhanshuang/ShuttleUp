import pytest
from sqlalchemy import select
from shuttleup.models import GuestRecovery, WebSession, EmailIdentity, now_ms
from shuttleup.security import token_hash

pytestmark = pytest.mark.asyncio

async def test_recovery_keeps_identity_rotates_code_and_revokes_sessions(client):
    guest = (await client.post('/api/v1/auth/guest', json={'display_name': '球友'})).json()
    raw = guest['recovery_code']
    old_cookies = dict(client.cookies)
    with client.testing_session_factory() as db:
        assert db.get(GuestRecovery, guest['user']['id']).code_hash == token_hash(raw)
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':raw})).status_code == 409
    client.cookies.clear()
    response = await client.post('/api/v1/auth/guest/recover', json={'recovery_code':raw})
    assert response.status_code == 200
    recovered = response.json()
    assert recovered['user']['id'] == guest['user']['id']
    assert recovered['recovery_code'] != raw
    assert response.headers['cache-control'] == 'no-store'
    client.cookies.clear()
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':raw})).status_code == 422
    client.cookies.update(old_cookies)
    assert (await client.get('/api/v1/session')).json()['user'] is None
    client.cookies.clear()
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':recovered['recovery_code']})).status_code == 200

async def test_existing_guest_generates_code_with_csrf(client):
    guest = (await client.post('/api/v1/auth/guest', json={'display_name':'已有游客'})).json()
    with client.testing_session_factory() as db:
        db.delete(db.get(GuestRecovery, guest['user']['id']))
        db.commit()
    assert (await client.post('/api/v1/me/guest-recovery')).status_code == 403
    response = await client.post('/api/v1/me/guest-recovery', headers={'X-CSRF-Token':guest['csrf_token']})
    assert response.status_code == 200
    first = response.json()['recovery_code']
    second = (await client.post('/api/v1/me/guest-recovery', headers={'X-CSRF-Token':guest['csrf_token']})).json()['recovery_code']
    client.cookies.clear()
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':first})).status_code == 422
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':second})).json()['user']['id'] == guest['user']['id']

async def test_guest_sliding_session_does_not_resurrect_expired_cookie(client):
    guest = (await client.post('/api/v1/auth/guest', json={'display_name':'续期'})).json()
    with client.testing_session_factory() as db:
        row = db.scalar(select(WebSession))
        row.expires_at = now_ms() + 3600_000
        db.commit()
    response = await client.get('/api/v1/session')
    assert response.json()['user']['id'] == guest['user']['id']
    assert 'Max-Age=2592000' in response.headers['set-cookie']
    with client.testing_session_factory() as db:
        row = db.scalar(select(WebSession))
        assert row.expires_at > now_ms() + 29 * 86400_000
        row.expires_at = now_ms() - 1
        db.commit()
    response = await client.get('/api/v1/session')
    assert response.json()['user'] is None
    assert 'set-cookie' not in response.headers

async def test_bound_email_invalidates_guest_recovery(client):
    guest = (await client.post('/api/v1/auth/guest', json={'display_name':'已绑定'})).json()
    with client.testing_session_factory() as db:
        db.add(EmailIdentity(email='bound@example.com', user_id=guest['user']['id'], verified_at=now_ms()))
        db.commit()
    assert (await client.post('/api/v1/me/guest-recovery', headers={'X-CSRF-Token':guest['csrf_token']})).status_code == 403
    client.cookies.clear()
    assert (await client.post('/api/v1/auth/guest/recover', json={'recovery_code':guest['recovery_code']})).status_code == 422
