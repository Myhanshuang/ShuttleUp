import pytest
from shuttleup.auth import email as mail
from shuttleup.models import EmailChallenge

pytestmark = pytest.mark.asyncio

@pytest.fixture
def outbox(monkeypatch):
    settings = mail.get_settings().model_copy(update={'smtp_host': 'smtp.example.com', 'smtp_from': 'sender@example.com'})
    monkeypatch.setattr(mail, 'get_settings', lambda: settings)
    sent = []
    monkeypatch.setattr(mail, 'send_code', lambda address, code: sent.append((address, code)))
    return sent

async def issue(client, outbox, address='player@example.com'):
    response = await client.post('/api/v1/auth/email/code', json={'email': address})
    assert response.status_code == 202, response.text
    return {'email': address, 'challenge_id': response.json()['challenge_id'], 'code': outbox[-1][1],
            'password': 'long-enough-password', 'display_name': '球友'}

async def test_verified_registration_login_and_replay(client, outbox):
    body = await issue(client, outbox, 'Player@EXAMPLE.COM')
    result = await client.post('/api/v1/auth/email/register', json=body)
    assert result.status_code == 201, result.text
    assert result.json()['user']['email'] == 'player@example.com'
    user_id = result.json()['user']['id']
    client.cookies.clear()
    assert (await client.post('/api/v1/auth/email/register', json=body)).status_code == 422
    assert (await client.post('/api/v1/auth/email/code', json={'email': body['email']})).status_code == 409
    logged = await client.post('/api/v1/auth/login', json={'username': 'PLAYER@example.com', 'password': body['password']})
    assert logged.status_code == 200
    assert logged.json()['user']['id'] == user_id
    assert (await client.post('/api/v1/auth/login', json={'username': body['email'], 'password': 'wrong'})).status_code == 401

async def test_guest_upgrade_preserves_identity_and_requires_csrf(client, outbox):
    guest = (await client.post('/api/v1/auth/guest', json={'display_name': '游客'})).json()
    assert (await client.post('/api/v1/auth/email/code', json={'email': 'player@example.com'})).status_code == 403
    client.headers['x-csrf-token'] = guest['csrf_token']
    body = await issue(client, outbox)
    result = await client.post('/api/v1/auth/email/register', json=body)
    assert result.status_code == 201, result.text
    assert result.json()['user']['id'] == guest['user']['id']
    assert (await client.get('/api/v1/session')).json()['user']['email'] == body['email']
    assert (await client.post('/api/v1/auth/register', json={'username': 'replacement', 'password': body['password']})).status_code == 403

async def test_cooldown_and_guess_limit(client, outbox):
    body = await issue(client, outbox)
    assert (await client.post('/api/v1/auth/email/code', json={'email': body['email']})).status_code == 429
    wrong = '000000' if body['code'] != '000000' else '111111'
    for _ in range(5):
        assert (await client.post('/api/v1/auth/email/register', json={**body, 'code': wrong})).status_code == 422
    assert (await client.post('/api/v1/auth/email/register', json=body)).status_code == 422

async def test_expiration_and_owner_binding(client, outbox):
    body = await issue(client, outbox)
    guest = (await client.post('/api/v1/auth/guest', json={'display_name': '游客'})).json()
    client.headers['x-csrf-token'] = guest['csrf_token']
    assert (await client.post('/api/v1/auth/email/register', json=body)).status_code == 422
    client.cookies.clear()
    with client.testing_session_factory() as db:
        db.get(EmailChallenge, body['challenge_id']).expires_at = 0
        db.commit()
    assert (await client.post('/api/v1/auth/email/register', json=body)).status_code == 422

async def test_unconfigured_and_delivery_failure(client, outbox, monkeypatch):
    monkeypatch.setattr(mail, 'configured', lambda: False)
    assert (await client.get('/api/v1/auth/options')).json()['email_registration'] is False
    assert (await client.post('/api/v1/auth/email/code', json={'email': 'player@example.com'})).status_code == 503
    monkeypatch.setattr(mail, 'configured', lambda: True)
    def broken(*args): raise RuntimeError('secret SMTP password')
    monkeypatch.setattr(mail, 'send_code', broken)
    for _ in range(5):
        response = await client.post('/api/v1/auth/email/code', json={'email': 'player@example.com'})
        assert response.status_code == 503
        assert 'secret' not in response.text
    assert (await client.post('/api/v1/auth/email/code', json={'email': 'player@example.com'})).status_code == 429

async def test_validation_does_not_echo_password_or_code(client):
    response = await client.post('/api/v1/auth/email/register', json={
        'email': 'player@example.com', 'challenge_id': 'a'*36, 'code': 'sensitive-code',
        'password': 'secret', 'display_name': '球友'})
    assert response.status_code == 422
    assert 'sensitive-code' not in response.text
    assert 'secret' not in response.text

@pytest.mark.parametrize('security', ['ssl', 'starttls'])
async def test_smtp_transport(client, monkeypatch, security):
    settings = mail.get_settings().model_copy(update={
        'smtp_host':'smtp.example.com', 'smtp_port':465 if security == 'ssl' else 587,
        'smtp_security':security, 'smtp_username':'sender@example.com',
        'smtp_password':'app-password', 'smtp_from':'sender@example.com'})
    monkeypatch.setattr(mail, 'get_settings', lambda: settings)
    calls = []
    class SMTP:
        def __init__(self, host, port, **kwargs): calls.append((host, port))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, **kwargs): calls.append('tls')
        def login(self, username, password): calls.append((username, password))
        def send_message(self, message):
            assert message['To'] == 'player@example.com'
            assert message['From'] == 'sender@example.com'
            assert '123456' in message.get_content()
            calls.append('sent')
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setattr(mail.smtplib, 'SMTP', SMTP)
    mail.send_code('player@example.com', '123456')
    assert ('sender@example.com', 'app-password') in calls
    assert ('tls' in calls) == (security == 'starttls')
    assert calls[-1] == 'sent'

async def test_designated_admin_requires_verified_email(client, outbox, monkeypatch):
    settings = mail.get_settings().model_copy(update={'bootstrap_admin_email':'admin@example.com'})
    monkeypatch.setattr(mail, 'get_settings', lambda: settings)
    body = await issue(client, outbox, 'ADMIN@example.com')
    wrong = '000000' if body['code'] != '000000' else '111111'
    assert (await client.post('/api/v1/auth/email/register', json={**body,'code':wrong})).status_code == 422
    assert (await client.get('/api/v1/session')).json()['user'] is None
    registered = await client.post('/api/v1/auth/email/register', json=body)
    assert registered.status_code == 201
    assert registered.json()['user']['is_admin'] is True
    client.cookies.clear()
    other = await issue(client, outbox, 'other@example.com')
    result = await client.post('/api/v1/auth/email/register', json={**other, 'is_admin':True})
    assert result.status_code == 201
    assert result.json()['user']['is_admin'] is False
