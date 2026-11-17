import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, func

from shuttleup.config import get_settings
from shuttleup.models import Activity, AvailabilityRule, BotIdentity, Participant, User

pytestmark = pytest.mark.asyncio


async def command(client, cmd, sender="host", args=None, *, private=False, group="group-1", code=None, message=None):
    message = message or str(uuid.uuid4())
    return await client.post('/bot/v1/commands', headers={"Authorization": f"Bearer {get_settings().astrbot_main_token}", "Idempotency-Key": f"astrbot:qq:{message}"}, json={"bot_key": "main", "platform_id": "qq", "sender_id": sender, "sender_name": f"球友-{sender}", "umo": f"qq:FriendMessage:{sender}" if private else f"qq:GroupMessage:{group}", "message_id": message, "command": cmd, "args": args or {}, "is_private": private, "activity_code": code})


async def test_first_bot_command_creates_activity_and_web_uses_same_identity(client):
    first = await command(client, 'activity.create', args={"title": "群内首场"}, message="same")
    assert first.status_code == 200, first.text
    duplicate = await command(client, 'activity.create', args={"title": "群内首场"}, message="same")
    assert duplicate.json() == first.json()
    with client.testing_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Activity)) == 1
        activity = db.scalar(select(Activity))
        aid = activity.id
        assert db.scalar(select(User).where(User.id == activity.host_user_id)).display_name == '球友-host'
    assert (await command(client, 'participant.join', sender='member')).status_code == 200
    personal = await command(client, 'web.open', private=True)
    path = personal.json()['reply']['links'][0]['path']
    token = parse_qs(urlparse(path).fragment)['token'][0]
    logged = await client.post('/api/v1/auth/bot-login', json={'token': token})
    assert logged.status_code == 200, logged.text
    assert (await client.post('/api/v1/auth/bot-login', json={'token': token})).status_code == 422
    listed = (await client.get('/api/v1/activities')).json()['items']
    assert listed[0]['id'] == aid and listed[0]['is_host'] and listed[0]['participant_count'] == 1
    assert (await command(client, 'web.open')).json()['reply']['links'] == []


async def test_bot_permission_validation_and_atomicity(client):
    failed = await command(client, 'activity.create', args={'title': ''})
    assert failed.status_code == 422
    with client.testing_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
    await command(client, 'activity.create', args={'title': '共享活动'})
    await command(client, 'participant.join', sender='member')
    with client.testing_session_factory() as db:
        activity = db.scalar(select(Activity)); aid, code = activity.id, activity.short_code
    forbidden = await command(client, 'activity.open_cancel', sender='member', args={'reason': '取消'})
    assert forbidden.status_code == 403
    foreign = await command(client, 'activity.current', sender='host', group='another', code=code)
    assert foreign.status_code == 403
    invalid = await command(client, 'availability.set', args={'date': '2026-09-19', 'time': '22:00-18:00', 'state': 'free'})
    assert invalid.status_code == 422
    good = await command(client, 'availability.set', args={'date': '2026-09-19', 'time': '18:00-20:00', 'state': 'free'})
    assert good.status_code == 200, good.text
    with client.testing_session_factory() as db:
        rules = db.scalars(select(AvailabilityRule)).all()
        assert len(rules) == 1 and rules[0].activity_id == aid
    # Browser headers cannot impersonate the internally authenticated helper principal.
    client.cookies.clear()
    assert (await client.get('/api/v1/activities', headers={'helper_user_id': 'host'})).status_code == 401


async def test_bot_uses_web_billing_guards(client):
    await command(client, 'activity.create', args={'title': '费用'})
    await command(client, 'participant.join', sender='member')
    negative = await command(client, 'expense.create', args={'kind': '球费', 'value': '-1'})
    assert negative.status_code == 422
    with client.testing_session_factory() as db:
        activity = db.scalar(select(Activity)); activity.billing_status = 'issued'; db.commit()
    frozen = await command(client, 'expense.create', args={'kind': '球费', 'value': '30'})
    assert frozen.status_code == 409 and frozen.json()['detail']['code'] == 'BILL_NOT_DRAFT'


async def test_bind_is_optional_private_and_does_not_orphan_bot_data(client):
    web = await client.post('/api/v1/auth/guest', json={'display_name': 'web_user'})
    csrf = web.json()['csrf_token']
    code = (await client.post('/api/v1/me/bot-bind-token', headers={'X-CSRF-Token': csrf})).json()['code']
    assert (await command(client, 'identity.bind', args={'code': code})).status_code == 422
    assert (await command(client, 'identity.bind', args={'code': code}, private=True)).status_code == 200
    await command(client, 'activity.create', args={'title': '绑定用户创建'})
    assert (await client.get('/api/v1/activities')).json()['items'][0]['title'] == '绑定用户创建'
    await command(client, 'activity.create', sender='other', args={'title': '独立身份'})
    code = (await client.post('/api/v1/me/bot-bind-token', headers={'X-CSRF-Token': csrf})).json()['code']
    assert (await command(client, 'identity.bind', sender='other', args={'code': code}, private=True)).status_code == 409


async def test_visual_time_batch_last_stroke_wins_and_requires_membership(client):
    guest = await client.post('/api/v1/auth/guest', json={'display_name': '时间编辑'})
    headers = {'X-CSRF-Token': guest.json()['csrf_token']}
    base = {'source': 'one_off', 'kind': 'once', 'start_at': '2026-09-19T18:00:00+08:00', 'end_at': '2026-09-19T20:00:00+08:00'}
    result = await client.post('/api/v1/me/availability/rules', headers=headers, json={'expected_revision': 0, 'rules': [{**base, 'state': 'free'}, {**base, 'state': 'busy'}]})
    assert result.status_code == 201
    result = await client.get('/api/v1/me/availability', params={'from_': base['start_at'], 'to': base['end_at']})
    assert result.json()['resolved'][0]['state'] == 'busy'
    await command(client, 'activity.create', args={'title': '他人活动'})
    with client.testing_session_factory() as db:
        aid = db.scalar(select(Activity.id))
    denied = await client.post('/api/v1/me/availability/rules', headers=headers, json={'expected_revision': result.json()['revision'], 'rules': [{**base, 'state': 'free', 'source': 'activity', 'activity_id': aid}]})
    assert denied.status_code == 403


async def test_invalid_weekly_rule_returns_validation_error(client):
    guest = await client.post('/api/v1/auth/guest', json={'display_name': '校验'})
    result = await client.post('/api/v1/me/availability/rules', headers={'X-CSRF-Token': guest.json()['csrf_token']}, json={'expected_revision': 0, 'rules': [{'state': 'free', 'source': 'weekly', 'kind': 'weekly', 'recurrence': {'weekdays': [9]}}]})
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'VALIDATION_ERROR'


async def test_qq_can_bind_identity_in_group_and_reuse_across_groups(client):
    first = await command(client, 'identity.create', args={'display_name': '小林'}, message='bind-qq')
    assert first.status_code == 200 and '已为当前 QQ 绑定身份「小林」' in first.json()['reply']['text']
    duplicate = await command(client, 'identity.create', args={'display_name': '小林'}, message='bind-qq')
    assert duplicate.json() == first.json()
    again = await command(client, 'identity.create', args={'display_name': '不能覆盖'}, group='group-2')
    assert '当前 QQ 已绑定身份「小林」' in again.json()['reply']['text']
    with client.testing_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        identity = db.scalar(select(BotIdentity)); uid = identity.user_id
    await command(client, 'activity.create', args={'title': '绑定后发起'})
    await command(client, 'identity.create', sender='another', args={'display_name': '小林'})
    with client.testing_session_factory() as db:
        assert db.scalar(select(Activity)).host_user_id == uid
        assert db.scalar(select(func.count()).select_from(User)) == 2


async def test_uncertain_time_is_persisted_separately_from_unset_time(client):
    guest = await client.post('/api/v1/auth/guest', json={'display_name': '不确定时间'})
    response = await client.post('/api/v1/me/availability/rules', headers={'X-CSRF-Token': guest.json()['csrf_token']}, json={'expected_revision': 0, 'rules': [{'source': 'one_off', 'kind': 'once', 'state': 'uncertain', 'start_at': '2026-09-19T18:00:00+08:00', 'end_at': '2026-09-19T20:00:00+08:00'}]})
    assert response.status_code == 201
    resolved = (await client.get('/api/v1/me/availability', params={'from_': '2026-09-19T17:00:00+08:00', 'to': '2026-09-19T21:00:00+08:00'})).json()['resolved']
    assert [s['state'] for s in resolved] == ['unknown', 'uncertain', 'unknown']
