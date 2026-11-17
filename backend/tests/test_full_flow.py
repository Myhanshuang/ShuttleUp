from conftest import join_times
from datetime import datetime
import uuid

import httpx
import pytest
from sqlalchemy import select

from shuttleup.app import app
from shuttleup.models import ProviderConfig, User, Venue

pytestmark=pytest.mark.asyncio


async def make_guest(client,name):
    data=(await client.post('/api/v1/auth/guest',json={'display_name':name})).json()
    return data['user'],data['csrf_token']


async def test_four_player_activity_to_partial_payments_and_archive(client, monkeypatch):
    from shuttleup.venues import routes as venue_routes
    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            from datetime import timezone
            instant = datetime(2026, 9, 19, 0, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(venue_routes, "datetime", FixtureDateTime)
    host,host_csrf=await make_guest(client,'A')
    with client.testing_session_factory.begin() as db:
        db.get(User,host['id']).is_admin=True
        provider=ProviderConfig(key='manual-test',adapter_key='manual',label='人工测试源',config={},fresh_for_seconds=600);db.add(provider);db.flush()
        venue=Venue(provider_id=provider.id,external_venue_id='gym-a',name='A馆',address='测试路1号',booking_url='https://venue.invalid/book');db.add(venue);db.flush();venue_id=venue.id
    created=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':host_csrf},json={'title':'完整四人场','date_from':'2026-09-19','date_to':'2026-09-19','daily_windows':[{'weekdays':[6],'start_time':'18:00','end_time':'22:00'}],'min_players':4,'max_players':4,'venue_preferences':[venue_id]})).json();aid=created['id'];token=created['invite_token']
    others=[]
    for name in ['B','C','D']:
        c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver');user,csrf=await make_guest(c,name);joined=(await c.post(f'/api/v1/invites/{token}/join',json={'availability': await join_times(client, token)})).json();others.append((name,c,user,joined['activity']['my_participant_id'],csrf))
    host_pid=created['my_participant_id']
    for _,c,_,_,csrf in [('A',client,host,host_pid,host_csrf),*others]:
        response=await c.post('/api/v1/me/availability/rules',headers={'X-CSRF-Token':csrf},json={'rules':[{'state':'free','source':'activity','kind':'once','start_at':'2026-09-19T18:00:00+08:00','end_at':'2026-09-19T20:00:00+08:00','activity_id':aid}],'expected_revision':0 if c is client else 1});assert response.status_code==201
    now=datetime.now().astimezone().isoformat()
    slots={'schema_version':1,'external_venue_id':'gym-a','local_date':'2026-09-19','timezone':'Asia/Shanghai','fetched_at':now,'coverage':{'starts_at':'2026-09-19T08:00:00+08:00','ends_at':'2026-09-19T22:00:00+08:00','complete':True,'identity_mode':'court'},'slots':[{'external_slot_id':'c1-18','court_id':'c1','court_name':'1号场','starts_at':'2026-09-19T18:00:00+08:00','ends_at':'2026-09-19T19:00:00+08:00','status':'available','price_cents':6000,'remaining_count':1},{'external_slot_id':'c1-19','court_id':'c1','court_name':'1号场','starts_at':'2026-09-19T19:00:00+08:00','ends_at':'2026-09-19T20:00:00+08:00','status':'available','price_cents':6000,'remaining_count':1}]}
    assert (await client.put(f'/api/v1/settings/venues/{venue_id}/manual-slots',headers={'X-CSRF-Token':host_csrf},json=slots)).status_code==200
    activity=(await client.get(f'/api/v1/activities/{aid}')).json();candidate=(await client.get(f'/api/v1/activities/{aid}/candidates')).json()['candidates'][0];pids=[host_pid,*[x[3] for x in others]]
    plan=(await client.post(f'/api/v1/activities/{aid}/plans',headers={'X-CSRF-Token':host_csrf},json={'candidate_id':candidate['id'],'roster_participant_ids':pids,'expected_version':activity['version']})).json()
    activity=(await client.get(f'/api/v1/activities/{aid}')).json();booking=(await client.post(f'/api/v1/activities/{aid}/bookings',headers={'X-CSRF-Token':host_csrf},json={'venue_id':venue_id,'court_ids':['c1'],'starts_at':plan['starts_at'],'ends_at':plan['ends_at'],'booker_participant_id':host_pid,'expected_version':activity['version']})).json();assert booking['activity_status']=='confirmed'
    await client.post(f"/api/v1/activities/{aid}/bookings/{booking['id']}/payment",headers={'X-CSRF-Token':host_csrf,'Idempotency-Key':str(uuid.uuid4())},json={'amount_cents':12000,'payer_participant_id':host_pid})
    participant_clients=[('A',client,host_pid,host_csrf),*[(name,c,pid,csrf) for name,c,_,pid,csrf in others]]
    for _,c,_,csrf in participant_clients: assert (await c.put(f'/api/v1/activities/{aid}/rsvp',headers={'X-CSRF-Token':csrf},json={'plan_id':plan['id'],'response':'yes'})).status_code==200
    entries=[{'participant_id':pid,'state':'present'} for pid in pids]
    await client.put(f'/api/v1/activities/{aid}/attendance',headers={'X-CSRF-Token':host_csrf},json={'entries':entries,'verify':True})
    activity=(await client.get(f'/api/v1/activities/{aid}')).json();await client.post(f'/api/v1/activities/{aid}/finish',headers={'X-CSRF-Token':host_csrf},json={'expected_version':activity['version']})
    expense_headers={'X-CSRF-Token':host_csrf,'Idempotency-Key':str(uuid.uuid4())}
    await client.post(f'/api/v1/activities/{aid}/expenses',headers=expense_headers,json={'kind':'shuttle','description':'球','amount_cents':4800,'payer_participant_id':pids[1],'split_mode':'equal','split_scope':'attendees','shares':[]})
    await client.post(f'/api/v1/activities/{aid}/expenses',headers={'X-CSRF-Token':host_csrf,'Idempotency-Key':str(uuid.uuid4())},json={'kind':'extra','description':'停车','amount_cents':2000,'payer_participant_id':pids[2],'split_mode':'equal','split_scope':'selected','shares':[{'participant_id':pids[0]},{'participant_id':pids[2]}]})
    activity=(await client.get(f'/api/v1/activities/{aid}')).json();published=(await client.post(f'/api/v1/activities/{aid}/bill/publish',headers={'X-CSRF-Token':host_csrf,'Idempotency-Key':str(uuid.uuid4())},json={'expected_generation':activity['bill_generation']})).json();assert list(published['snapshot']['balances_at_publish'].values())==[6800,600,-3200,-4200]
    transfers=published['snapshot']['transfers'];clients_by_pid={pid:(c,csrf) for _,c,pid,csrf in participant_clients}
    for transfer in transfers:
        payer,payer_csrf=clients_by_pid[transfer['from_participant_id']];receiver,receiver_csrf=clients_by_pid[transfer['to_participant_id']];parts=[2000,transfer['amount_cents']-2000] if transfer['amount_cents']==4200 else [transfer['amount_cents']]
        for amount in parts:
            claim=(await payer.post(f'/api/v1/activities/{aid}/payments',headers={'X-CSRF-Token':payer_csrf,'Idempotency-Key':str(uuid.uuid4())},json={'bill_revision_id':published['id'],'transfer_id':transfer['id'],'amount_cents':amount})).json();confirmed=await receiver.post(f"/api/v1/activities/{aid}/payments/{claim['id']}/confirm",headers={'X-CSRF-Token':receiver_csrf,'Idempotency-Key':str(uuid.uuid4())});assert confirmed.status_code==200
    final=(await client.get(f'/api/v1/activities/{aid}')).json();assert final['billing_status']=='settled';archived=await client.post(f'/api/v1/activities/{aid}/archive',headers={'X-CSRF-Token':host_csrf},json={'expected_version':final['version']});assert archived.status_code==200
    for _,c,_,_,_ in others:await c.aclose()

