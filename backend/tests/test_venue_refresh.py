from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from shuttleup.models import ProviderConfig, Venue, VenueSnapshot
from shuttleup.venues.providers import VenueSourceError, VenueDayResult


def sample_day(day):
    start=f'{day}T08:00:00+08:00'; middle=f'{day}T08:30:00+08:00'; end=f'{day}T09:00:00+08:00'
    return VenueDayResult.model_validate({'external_venue_id':'test-court','local_date':day,
        'timezone':'Asia/Shanghai','fetched_at':datetime.now(ZoneInfo('Asia/Shanghai')),
        'coverage':{'starts_at':start,'ends_at':end,'complete':True,'identity_mode':'court'},
        'slots':[{'external_slot_id':str(i),'court_id':'court-1','starts_at':a,'ends_at':b,
                  'status':status,'price_cents':1250} for i,(a,b,status) in enumerate([
                      (start,middle,'available'),(middle,end,'unavailable')])]})

pytestmark = pytest.mark.asyncio


async def setup(client):
    identity=(await client.post('/api/v1/auth/guest',json={'display_name':'查询者'})).json()
    with client.testing_session_factory.begin() as db:
        provider=ProviderConfig(key='test-source',adapter_key='standard_json',label='测试来源',config={'endpoint':'https://example.invalid','allowed_host':'example.invalid'})
        db.add(provider);db.flush()
        venue=Venue(provider_id=provider.id,external_venue_id='test-court',name='测试球馆')
        db.add(venue);db.flush();vid=venue.id
    return vid,datetime.now(ZoneInfo('Asia/Shanghai')).date(),identity['csrf_token']


async def test_fetch_cache_and_refresh_respect_cooldown(client,monkeypatch):
    vid,day,csrf=await setup(client);calls=[]
    async def fetch(self,external,query_day):
        calls.append(query_day);return sample_day(query_day)
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',fetch)
    response=await client.get(f'/api/v1/venues/{vid}/slots',params={'date':day.isoformat()})
    assert response.status_code==200,response.text
    assert response.json()['fresh'] and response.json()['available_count']==1
    again=await client.post(f'/api/v1/venues/{vid}/refresh',params={'date':day.isoformat()},headers={'X-CSRF-Token':csrf})
    assert again.status_code==202 and len(calls)==1
    assert (await client.post(f'/api/v1/venues/{vid}/refresh',params={'date':day.isoformat()})).status_code==403


async def test_first_failure_saved_and_does_not_retry_immediately(client,monkeypatch):
    vid,day,_=await setup(client);calls=[]
    async def fetch(*args):
        calls.append(1);raise VenueSourceError('AUTH_EXPIRED')
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',fetch)
    for _ in range(2):
        response=await client.get(f'/api/v1/venues/{vid}/slots',params={'date':day.isoformat()})
        assert response.status_code==200
        assert response.json()['last_error_code']=='AUTH_EXPIRED'
        assert not response.json()['fresh'] and response.json()['available_count']==0
    assert len(calls)==1


async def test_failed_refresh_retains_but_invalidates_previous_data(client,monkeypatch):
    vid,day,_=await setup(client)
    async def good(self,external,query_day):return sample_day(query_day)
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',good)
    await client.get(f'/api/v1/venues/{vid}/slots',params={'date':day.isoformat()})
    with client.testing_session_factory.begin() as db:
        row=db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id==vid))
        row.last_success_at=1;row.last_attempt_at=0;row.next_poll_at=0
    async def bad(*args):raise VenueSourceError('SOURCE_TIMEOUT')
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',bad)
    data=(await client.get(f'/api/v1/venues/{vid}/slots',params={'date':day.isoformat()})).json()
    assert len(data['slots'])==2 and not data['fresh'] and data['available_count']==0
    assert data['last_error_code']=='SOURCE_TIMEOUT'


async def test_expired_source_pauses_all_dates_until_credential_changes(client,monkeypatch):
    from datetime import timedelta
    from shuttleup.venues.login import paused
    vid,day,_=await setup(client);calls=[]
    with client.testing_session_factory.begin() as db:
        venue=db.get(Venue,vid);provider=db.get(ProviderConfig,venue.provider_id)
        provider.credential_env='VENUE_TEST_TOKEN'
    monkeypatch.setenv('VENUE_TEST_TOKEN','old')
    async def fetch(*args):calls.append(1);raise VenueSourceError('AUTH_EXPIRED')
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',fetch)
    for query_day in (day,day+timedelta(days=1)):
        data=(await client.get(f'/api/v1/venues/{vid}/slots',params={'date':query_day.isoformat()})).json()
        assert data['last_error_code']=='AUTH_EXPIRED'
    assert len(calls)==1
    with client.testing_session_factory.begin() as db:
        for row in db.scalars(select(VenueSnapshot)):
            row.last_attempt_at=0
        venue=db.get(Venue,vid);assert paused(db.get(ProviderConfig,venue.provider_id))
    monkeypatch.setenv('VENUE_TEST_TOKEN','new')
    async def good(self,external,query_day):calls.append(1);return sample_day(query_day)
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',good)
    result=(await client.get(f'/api/v1/venues/{vid}/slots',params={'date':day.isoformat()})).json()
    assert result['fresh'] and len(calls)==2
    with client.testing_session_factory() as db:
        venue=db.get(Venue,vid);assert not paused(db.get(ProviderConfig,venue.provider_id))


async def test_login_controls_require_admin_and_csrf(client,monkeypatch):
    from types import SimpleNamespace
    from shuttleup.models import User
    vid,day,csrf=await setup(client)
    with client.testing_session_factory() as db:pid=db.get(Venue,vid).provider_id
    path=f'/api/v1/settings/providers/{pid}/login'
    assert (await client.get(path)).status_code==403
    assert (await client.post(path,headers={'X-CSRF-Token':csrf})).status_code==403
    with client.testing_session_factory.begin() as db:
        user=db.scalar(select(User));user.is_admin=True
    calls=[]
    extension=SimpleNamespace(start_login=lambda:calls.append('start'),cancel_login=lambda:calls.append('cancel'),login_status=lambda:{'phase':'waiting'})
    monkeypatch.setattr('shuttleup.venues.routes.extension_for',lambda key:extension)
    monkeypatch.setattr('shuttleup.venues.login.extension_for',lambda key:extension)
    assert (await client.post(path)).status_code==403
    assert (await client.get(path)).json()['supported']
    assert (await client.post(path,headers={'X-CSRF-Token':csrf})).status_code==200
    assert (await client.delete(path,headers={'X-CSRF-Token':csrf})).status_code==200
    assert calls==['start','cancel']


async def test_missing_optional_extensions_do_not_break_builtin_provider(monkeypatch):
    from shuttleup.venues.providers import build_provider, supported_provider
    monkeypatch.setattr('shuttleup.venues.local.extensions',lambda:[])
    assert supported_provider('standard_json') and not supported_provider('private-source')
    with pytest.raises(VenueSourceError,match='ADAPTER_UNAVAILABLE'):
        build_provider('private-source',{})


async def test_check_candidates_fetches_source_and_returns_diagnostics(client,monkeypatch):
    vid,day,csrf=await setup(client);calls=[]
    async def fetch(self,external,query_day):
        calls.append(query_day);return sample_day(query_day)
    monkeypatch.setattr('shuttleup.venues.providers.StandardJsonProvider.fetch_day',fetch)
    a=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':csrf},json={
        'title':'刷新方案','venue_preferences':[vid],'date_from':day.isoformat(),'date_to':day.isoformat()})).json()
    path=f"/api/v1/activities/{a['id']}/candidates"
    assert (await client.get(path)).status_code==200 and not calls
    result=await client.post(path+'/refresh',headers={'X-CSRF-Token':csrf})
    assert result.status_code==200 and calls==[day]
    assert all(d['code']!='NO_DATA' for d in result.json()['diagnostics'])
