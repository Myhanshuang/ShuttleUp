from conftest import join_times
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import pytest
from sqlalchemy import select
from shuttleup.models import Activity, AvailabilityRule, Participant, ProviderConfig, Venue, VenueSnapshot, now_ms

pytestmark=pytest.mark.asyncio

async def fixture(client):
    identity=(await client.post('/api/v1/auth/guest',json={'display_name':'主持人'})).json()
    headers={'X-CSRF-Token':identity['csrf_token']}
    day=(datetime.now(ZoneInfo('Asia/Shanghai')).date()+timedelta(days=1)).isoformat()
    with client.testing_session_factory.begin() as db:
        provider=ProviderConfig(key='preview',adapter_key='manual',label='测试',fresh_for_seconds=3600)
        db.add(provider);db.flush()
        venue=Venue(provider_id=provider.id,external_venue_id='test',name='测试球馆')
        db.add(venue);db.flush();vid=venue.id
        db.add(VenueSnapshot(venue_id=vid,local_date=day,revision=1,content_hash='x',last_attempt_at=now_ms(),last_success_at=now_ms(),next_poll_at=now_ms()+3600000,
            coverage={'complete':True,'identity_mode':'court'},slots=[{'external_slot_id':'one','court_id':'c1','starts_at':f'{day}T18:00:00+08:00','ends_at':f'{day}T19:00:00+08:00','status':'available','price_cents':2000}]))
    a=(await client.post('/api/v1/activities',headers=headers,json={'title':'预览活动','date_from':day,'date_to':day,'min_players':2,'max_players':2,'venue_preferences':[vid]})).json()
    return a,headers,day

async def test_preview_is_read_only_and_checks_real_continuity_roster_and_freshness(client):
    a,headers,day=await fixture(client)
    await client.post(f"/api/v1/activities/{a['id']}/participants/offline", headers=headers, json={'display_name':'线下成员'})
    # Offline participants have no availability; an optimistic preview must not count them.
    path=f"/api/v1/activities/{a['id']}"
    assert not (await client.get(path+'/candidates/preview?duration_minutes=60')).json()['candidates']
    async with httpx.AsyncClient(transport=client._transport,base_url='http://testserver') as other:
        joined=(await other.post(f"/api/v1/invites/{a['invite_token']}/join",json={'availability': await join_times(client, a['invite_token']),'display_name':'球友'})).json()
        body={'rules':[{'state':'free','source':'activity','activity_id':a['id'],'kind':'once','start_at':f'{day}T18:00:00+08:00','end_at':f'{day}T20:00:00+08:00'}],'expected_revision':0}
        assert (await client.post('/api/v1/me/availability/rules',headers=headers,json=body)).status_code==201
        assert (await other.post('/api/v1/me/availability/rules',headers={'X-CSRF-Token':joined['csrf_token']},json={**body,"expected_revision":1})).status_code==201
        before=(await client.get(path)).json()
        assert not (await client.get(path+'/candidates')).json()['candidates']
        preview=(await client.get(path+'/candidates/preview?duration_minutes=60')).json()
        assert len(preview['candidates'])==1 and preview['candidates'][0]['total_price_cents']==2000
        assert preview['original_duration_minutes']==120
        after=(await client.get(path)).json()
        assert after['duration_minutes']==120 and after['version']==before['version'] and after['current_plan'] is None
        assert (await other.patch(path,headers={'X-CSRF-Token':joined['csrf_token']},json={'duration_minutes':60,'expected_version':after['version']})).status_code==403
        assert (await client.get(path+'/candidates/preview?duration_minutes=47')).status_code==422
        with client.testing_session_factory.begin() as db:
            db.scalar(select(VenueSnapshot)).last_success_at=1
        assert not (await client.get(path+'/candidates/preview?duration_minutes=60')).json()['candidates']

async def test_range_restore_preserves_personal_and_outside_activity_overrides(client):
    a,headers,day=await fixture(client)
    def rule(state,source,start,end): return {'state':state,'source':source,'activity_id':a['id'] if source=='activity' else None,'kind':'once','start_at':f'{day}T{start}:00+08:00','end_at':f'{day}T{end}:00+08:00'}
    added=await client.post('/api/v1/me/availability/rules',headers=headers,json={'expected_revision':0,'rules':[rule('free','one_off','18:00','22:00'),rule('busy','activity','18:00','22:00')]})
    assert added.status_code==201
    restored=await client.post('/api/v1/me/availability/rules',headers=headers,json={'expected_revision':2,'rules':[rule('inherit','activity','19:00','20:00')]})
    assert restored.status_code==201
    query={'activity_id':a['id'],'from_':f'{day}T18:00:00+08:00','to':f'{day}T22:00:00+08:00'}
    data=(await client.get('/api/v1/me/availability',params=query)).json()
    assert [s['state'] for s in data['resolved']]==['busy','free','busy']
    assert [s['source'] for s in data['resolved']]==['activity','one_off','activity']
    assert [s['state'] for s in data['personal_resolved']]==['free']
    assert (await client.post('/api/v1/me/availability/rules',headers=headers,json={'expected_revision':2,'rules':[rule('inherit','activity','18:00','22:00')]})).status_code==409
    assert (await client.post('/api/v1/me/availability/rules',headers=headers,json={'expected_revision':3,'rules':[rule('inherit','one_off','18:00','22:00')]})).status_code==422

async def test_attention_is_viewer_specific_and_events_keep_other_activity_private(client):
    a,headers,day=await fixture(client)
    path=f"/api/v1/activities/{a['id']}"
    assert a['next_action']['needed'] and a['next_action']['label']=='填写本次空闲时间'
    async with httpx.AsyncClient(transport=client._transport,base_url='http://testserver') as other:
        joined=(await other.post(f"/api/v1/invites/{a['invite_token']}/join",json={'availability': await join_times(client, a['invite_token']),'display_name':'球友'})).json()
        h={'X-CSRF-Token':joined['csrf_token']}
        body={'expected_revision':0,'rules':[{'state':'uncertain','source':'activity','activity_id':a['id'],'kind':'once','start_at':f'{day}T18:00:00+08:00','end_at':f'{day}T19:00:00+08:00'}]}
        await other.post('/api/v1/me/availability/rules',headers=h,json={**body,"expected_revision":body['expected_revision']+1 if body['expected_revision']==0 else body['expected_revision']})
        task=(await other.get(path)).json()['next_action']
        assert not task['needed'] and '已填写' in task['label']
        b=(await other.post('/api/v1/activities',headers=h,json={'title':'私人另一场'})).json()
        body['expected_revision']=2;body['rules'][0]['activity_id']=b['id']
        await other.post('/api/v1/me/availability/rules',headers=h,json={**body,"expected_revision":body['expected_revision']+1 if body['expected_revision']==0 else body['expected_revision']})
        events=(await client.get(path+'/events')).json()['items']
        times=[e for e in events if e['type']=='availability.changed']
        assert len(times)==2 and all(e['payload']=={} and e['actor_name']=='球友' for e in times)
