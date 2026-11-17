import pytest
from shuttleup.models import User
from shuttleup.security import hash_password

pytestmark = pytest.mark.asyncio

async def test_username_registration_disabled_for_anonymous_and_guest(client):
    body = {"username": "lin_01", "password": "long-enough-password"}
    assert (await client.post('/api/v1/auth/register', json=body)).status_code == 403
    guest = (await client.post('/api/v1/auth/guest', json={'display_name': '小林'})).json()
    result = await client.post('/api/v1/auth/register', json=body)
    assert result.status_code == 403
    assert result.json()['detail']['code'] == 'REGISTRATION_DISABLED'
    current = (await client.get('/api/v1/session')).json()['user']
    assert current['id'] == guest['user']['id']
    assert current['username'] is None

async def test_existing_username_login_still_works(client):
    with client.testing_session_factory() as db:
        db.add(User(username='player', display_name='球友', password_hash=hash_password('long-enough-password')))
        db.commit()
    assert (await client.post('/api/v1/auth/login', json={'username':'player', 'password':'wrong-password'})).status_code == 401
    result = await client.post('/api/v1/auth/login', json={'username':'player', 'password':'long-enough-password'})
    assert result.status_code == 200
    assert result.json()['user']['username'] == 'player'
