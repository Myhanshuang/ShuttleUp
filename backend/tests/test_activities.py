from conftest import join_times
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
        joined = await other.post(f"/api/v1/invites/{token}/join", json={'availability': await join_times(client, token),"display_name": "成员"})
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
        joined = (await other.post(f"/api/v1/invites/{token}/join", json={'availability': await join_times(client, token),"display_name": "成员"})).json()
        result = await other.patch(f"/api/v1/activities/{created['id']}", headers={"X-CSRF-Token": joined["csrf_token"]}, json={"title": "越权", "expected_version": 2})
        assert result.status_code == 403


async def test_host_removal_blocks_invite_rejoin_and_can_restore(client):
    csrf=await guest(client,'主持人')
    activity=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':csrf},json={'title':'成员管理'})).json()
    aid=activity['id'];token=activity['invite_token']
    async with httpx.AsyncClient(transport=client._transport,base_url='http://testserver') as other:
        joined=(await other.post(f'/api/v1/invites/{token}/join',json={'availability': await join_times(client, token),'display_name':'成员'})).json()
        pid=joined['activity']['my_participant_id']
        current=(await client.get(f'/api/v1/activities/{aid}')).json()
        path=f'/api/v1/activities/{aid}/participants/{pid}'
        payload={'membership':'removed','expected_version':current['version']}
        assert (await other.patch(path,headers={'X-CSRF-Token':joined['csrf_token']},json=payload)).status_code==403
        assert (await client.patch(path,json=payload)).status_code==403
        removed=await client.patch(path,headers={'X-CSRF-Token':csrf},json=payload)
        assert removed.status_code==200 and removed.json()['membership']=='removed'
        assert (await other.get(f'/api/v1/activities/{aid}')).status_code==403
        assert (await other.post(f'/api/v1/invites/{token}/join',json={})).json()['detail']['code']=='MEMBER_REMOVED'
        restored=await client.patch(path,headers={'X-CSRF-Token':csrf},json={'membership':'active','expected_version':removed.json()['version']})
        assert restored.status_code==200
        assert (await other.get(f'/api/v1/activities/{aid}')).status_code==200
        cannot_remove_host=await client.patch(f"/api/v1/activities/{aid}/participants/{activity['my_participant_id']}",headers={'X-CSRF-Token':csrf},json={'membership':'removed','expected_version':restored.json()['version']})
        assert cannot_remove_host.status_code==409


async def test_closed_activity_preserves_members(client):
    from shuttleup.models import Activity
    csrf=await guest(client,'主持人')
    activity=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':csrf},json={'title':'管理员成员管理'})).json()
    aid=activity['id']
    offline=(await client.post(f'/api/v1/activities/{aid}/participants/offline',headers={'X-CSRF-Token':csrf},json={'display_name':'成员'})).json()
    with client.testing_session_factory.begin() as db:
        a=db.get(Activity,aid)
        a.status='finished'
    current=(await client.get(f'/api/v1/activities/{aid}')).json()
    response=await client.patch(f"/api/v1/activities/{aid}/participants/{offline['id']}",headers={'X-CSRF-Token':csrf},json={'membership':'removed','expected_version':current['version']})
    assert response.status_code==409


async def test_instance_admin_can_manage_members(client):
    from shuttleup.models import User
    csrf=await guest(client,'主持人')
    activity=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':csrf},json={'title':'管理员管理'})).json()
    aid=activity['id']
    member=(await client.post(f'/api/v1/activities/{aid}/participants/offline',headers={'X-CSRF-Token':csrf},json={'display_name':'成员'})).json()
    current=(await client.get(f'/api/v1/activities/{aid}')).json()
    async with httpx.AsyncClient(transport=client._transport,base_url='http://testserver') as other:
        identity=(await other.post('/api/v1/auth/guest',json={'display_name':'管理员'})).json()
        with client.testing_session_factory.begin() as db:
            db.get(User,identity['user']['id']).is_admin=True
        result=await other.patch(f"/api/v1/activities/{aid}/participants/{member['id']}",headers={'X-CSRF-Token':identity['csrf_token']},json={'membership':'removed','expected_version':current['version']})
        assert result.status_code==200 and result.json()['membership']=='removed'


async def test_activity_venue_selection_validated_and_editable(client):
    from shuttleup.models import Venue,ProviderConfig
    csrf=await guest(client,'主持人');headers={'X-CSRF-Token':csrf}
    with client.testing_session_factory.begin() as db:
        provider=ProviderConfig(key='manual-source',adapter_key='manual',label='人工')
        db.add(provider);db.flush();venue=Venue(provider_id=provider.id,external_venue_id='v',name='测试场馆')
        db.add(venue);db.flush();vid=venue.id
    bad=await client.post('/api/v1/activities',headers=headers,json={'title':'错误场馆','venue_preferences':['missing']})
    assert bad.status_code==422
    a=(await client.post('/api/v1/activities',headers=headers,json={'title':'待选场馆'})).json()
    path=f"/api/v1/activities/{a['id']}"
    result=(await client.get(path+'/candidates')).json()
    assert any(d['code']=='NO_VENUE' for d in result['diagnostics'])
    saved=await client.patch(path,headers=headers,json={'venue_preferences':[vid],'expected_version':a['version']})
    assert saved.status_code==200 and saved.json()['venue_preferences']==[vid]
    result=(await client.get(path+'/candidates')).json()
    assert any(d['code']=='NO_DATA' for d in result['diagnostics'])
    assert (await client.post(path+'/candidates/refresh')).status_code==403
    assert (await client.post(path+'/candidates/refresh',headers=headers)).status_code==200


async def test_host_adjusts_activity_schedule_without_changing_availability(client):
    from sqlalchemy import select
    from shuttleup.models import AvailabilityRule, Activity
    csrf=await guest(client,'主持人');headers={'X-CSRF-Token':csrf}
    activity=(await client.post('/api/v1/activities',headers=headers,json={'title':'调整时长','duration_minutes':120})).json()
    path=f"/api/v1/activities/{activity['id']}"
    with client.testing_session_factory.begin() as db:
        db.add(AvailabilityRule(user_id=activity['host_user_id'],activity_id=activity['id'],
            source='activity',state='free',kind='once',start_at=1789210800000,end_at=1789221600000,edit_seq=1))
    with client.testing_session_factory() as db:
        before=[(r.id,r.state,r.start_at,r.end_at) for r in db.scalars(select(AvailabilityRule))]
    changed=await client.patch(path,headers=headers,json={'duration_minutes':60,'daily_windows':[{'weekdays':[1,2,3,4,5,6,7],'start_time':'19:00','end_time':'21:00'}],'expected_version':activity['version']})
    assert changed.status_code==200 and changed.json()['duration_minutes']==60
    assert changed.json()['daily_windows'][0]['start_time']=='19:00'
    with client.testing_session_factory() as db:assert [(r.id,r.state,r.start_at,r.end_at) for r in db.scalars(select(AvailabilityRule))]==before
    invalid=await client.patch(path,headers=headers,json={'duration_minutes':0,'expected_version':changed.json()['version']})
    assert invalid.status_code==422
    invalid=await client.patch(path,headers=headers,json={'date_to':'2000-01-01','expected_version':changed.json()['version']})
    assert invalid.status_code==422
    with client.testing_session_factory.begin() as db:db.get(Activity,activity['id']).status='booking'
    blocked=await client.patch(path,headers=headers,json={'duration_minutes':90,'expected_version':changed.json()['version']})
    assert blocked.status_code==409
