import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from shuttleup.availability import wakeup, wakeup_client as client_module, wakeup_crypto as crypto
from shuttleup.models import AvailabilityRule, ScheduleImport


def share_payload():
    parts = [
        {'id': 1},
        [{'timeTable': 1, 'node': 1, 'startTime': '08:00', 'endTime': '08:45'},
         {'timeTable': 1, 'node': 2, 'startTime': '08:55', 'endTime': '09:40'}],
        {'startDate': '2026-9-7', 'maxWeek': 4, 'tableName': '示例学期'},
        [{'id': 1, 'courseName': '示例课程'}],
        [{'id': 1, 'day': 3, 'startWeek': 1, 'endWeek': 4, 'type': 1, 'startNode': 1, 'step': 2},
         {'id': 1, 'day': 5, 'startWeek': 1, 'endWeek': 4, 'type': 2, 'ownTime': True, 'startTime': '13:10', 'endTime': '14:20'}],
    ]
    return parts


def encode(parts):
    return json.dumps({'shareData': '\n'.join(json.dumps(x) for x in parts)}).encode()


def test_native_mapping_odd_even_custom_times_and_breaks():
    s = wakeup.WakeUpImporter().normalize(encode(share_payload()))
    occurrences = wakeup.expand_occurrences(s)
    assert len(occurrences) == 6
    assert occurrences[0]['starts_at'] == '2026-09-09T08:00:00+08:00'
    assert occurrences[0]['ends_at'] == '2026-09-09T08:45:00+08:00'
    assert occurrences[1]['starts_at'] == '2026-09-09T08:55:00+08:00'
    assert occurrences[2]['starts_at'] == '2026-09-18T13:10:00+08:00'
    assert s.term_end_date.isoformat() == '2026-10-04'


@pytest.mark.parametrize('mutation', ['backwards_time', 'unknown_period', 'invalid_day', 'invalid_week'])
def test_native_mapping_rejects_incomplete_or_invalid_schedules(mutation):
    parts = share_payload()
    if mutation == 'backwards_time': parts[1][0]['endTime'] = '07:30'
    if mutation == 'unknown_period': parts[4][0]['step'] = 3
    if mutation == 'invalid_day': parts[4][0]['day'] = 8
    if mutation == 'invalid_week': parts[4][0]['endWeek'] = 70
    with pytest.raises(client_module.WakeUpError): wakeup.WakeUpImporter().normalize(encode(parts))


@pytest.mark.asyncio
async def test_encrypted_handshake_fetch_and_expiry(monkeypatch):
    raw = encode(share_payload())
    code = '0123456789abcdef0123456789abcdef'
    token = 'abcdefghij'
    requests = []
    expired = False
    def handler(request):
        requests.append(request)
        form = parse_qs(request.content.decode())
        assert request.url.host == 'api.wakeup.fun' and 'key' not in str(request.url)
        if request.url.path == crypto.ANTISPAM_PATH:
            plain = crypto.native_des_decrypt(crypto.native_hex_decode(form['data'][0]), crypto.SIGN_A_KEY).decode()
            rand = plain.split('##')[1]
            sign_b = crypto.native_hex_encode(crypto.native_des_encrypt(rand + '##' + token, rand[:5] + '#G4'))
            return httpx.Response(200, json={'data': sign_b})
        key = crypto.native_get_key(str(client_module.VERSION), token)
        assert crypto.rc4_crypt(base64.b64decode(form['data'][0]), key).decode() == 'key=' + code
        encrypted = crypto.rc4_crypt(b'{"shareData":""}' if expired else raw, key)
        return httpx.Response(200, json={'errNo': 0, 'data': base64.b64encode(encrypted).decode()})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    response = await client_module.fetch_share(code)
    assert json.loads(response) == json.loads(raw)
    assert len(requests) == 2
    expired = True
    with pytest.raises(client_module.WakeUpError, match='分享已失效'):
        await client_module.fetch_share(code)


@pytest.mark.asyncio
async def test_preview_confirm_replace_and_delete_without_storing_course_names(client, monkeypatch):
    async def fetch(code): return encode(share_payload())
    monkeypatch.setattr(wakeup, 'fetch_share', fetch)
    identity = (await client.post('/api/v1/auth/guest', json={'display_name': '课表测试'})).json()
    headers = {'X-CSRF-Token': identity['csrf_token']}
    body = {'share_text': '分享口令为「0123456789abcdef0123456789abcdef」'}
    r = await client.post('/api/v1/me/imports/wakeup/preview', headers=headers, json=body)
    assert r.status_code == 200, r.text
    assert r.json()['summary'] == {'course_count': 1, 'occurrence_count': 6}
    with client.testing_session_factory() as db:
        assert db.scalar(select(AvailabilityRule)) is None
        assert db.scalar(select(ScheduleImport)) is None
    confirmed = await client.post('/api/v1/me/imports/wakeup/confirm', headers=headers, json={
        'preview_id': r.json()['preview_id'], 'label': '示例学期', 'expected_revision': 0})
    assert confirmed.status_code == 200, confirmed.text
    with client.testing_session_factory() as db:
        rules = db.scalars(select(AvailabilityRule)).all()
        assert len(rules) == 6 and all(x.state == 'busy' and x.source == 'course' for x in rules)
    second = await client.post('/api/v1/me/imports/wakeup/preview', headers=headers, json=body)
    replaced = await client.post('/api/v1/me/imports/wakeup/confirm', headers=headers, json={
        'preview_id': second.json()['preview_id'], 'label': '示例学期', 'expected_revision': 1})
    assert replaced.status_code == 200, replaced.text
    with client.testing_session_factory() as db:
        assert len(db.scalars(select(AvailabilityRule)).all()) == 6
    deleted = await client.delete(f"/api/v1/me/imports/{replaced.json()['id']}?expected_revision=2", headers=headers)
    assert deleted.status_code == 204
