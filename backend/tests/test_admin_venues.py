import pytest
from sqlalchemy import select
from shuttleup.models import User, ProviderConfig, Venue

pytestmark = pytest.mark.asyncio

async def setup_admin(client):
    guest=(await client.post('/api/v1/auth/guest', json={'display_name':'测试管理员'})).json()
    with client.testing_session_factory() as db:
        db.get(User,guest['user']['id']).is_admin=True
        source=ProviderConfig(key='admin-test',adapter_key='manual',label='人工来源',config={'secret':'not-returned'})
        db.add(source);db.commit();pid=source.id
    client.headers['X-CSRF-Token']=guest['csrf_token']
    return pid

async def test_management_permissions_and_source_secrets(client):
    assert (await client.get('/api/v1/settings/venues')).status_code == 401
    guest=(await client.post('/api/v1/auth/guest',json={'display_name':'普通球友'})).json()
    client.headers['X-CSRF-Token']=guest['csrf_token']
    assert (await client.get('/api/v1/settings/venues')).status_code == 403
    assert (await client.get('/api/v1/settings/venue-sources')).status_code == 403
    body={'provider_id':'none','external_venue_id':'gym','name':'球馆'}
    assert (await client.post('/api/v1/settings/venues',json=body)).status_code == 403
    assert (await client.put('/api/v1/settings/venues/missing',json={'name':'球馆','enabled':False,'expected_version':1})).status_code == 403
    pid=await setup_admin(client)
    result=await client.get('/api/v1/settings/venue-sources')
    assert result.status_code == 200
    assert 'not-returned' not in result.text and 'config' not in result.text
    client.headers.pop('X-CSRF-Token')
    assert (await client.post('/api/v1/settings/venues',json={**body,'provider_id':pid})).status_code == 403

async def test_create_edit_disable_reenable_and_conflicts(client):
    pid=await setup_admin(client)
    body={'provider_id':pid,'external_venue_id':'gym','name':'测试球馆','booking_url':'https://example.com/book','hourly_rate_cents':6000}
    result=await client.post('/api/v1/settings/venues',json=body)
    assert result.status_code == 201, result.text
    venue=result.json();vid=venue['id']
    assert (await client.post('/api/v1/settings/venues',json=body)).status_code == 409
    updated={'name':'新球馆名称','address':'新地址','booking_url':body['booking_url'],'hourly_rate_cents':8000,'enabled':False,'expected_version':venue['version']}
    response=await client.put(f'/api/v1/settings/venues/{vid}',json=updated)
    assert response.status_code == 200, response.text
    assert response.json()['name']=='新球馆名称'
    assert not (await client.get('/api/v1/venues')).json()['items']
    assert len((await client.get('/api/v1/settings/venues')).json()['items'])==1
    assert (await client.put(f'/api/v1/settings/venues/{vid}',json=updated)).status_code==409
    updated.update(enabled=True,expected_version=response.json()['version'])
    assert (await client.put(f'/api/v1/settings/venues/{vid}',json=updated)).status_code==200
    assert (await client.get('/api/v1/venues')).json()['items'][0]['id']==vid
    with client.testing_session_factory() as db:
        assert db.get(Venue,vid).external_venue_id=='gym'

async def test_venue_validation(client):
    pid=await setup_admin(client)
    body={'provider_id':pid,'external_venue_id':'gym','name':'球馆'}
    for changes in [{'name':'  '},{'booking_url':'javascript:alert(1)'},{'timezone':'Not/AZone'},{'hourly_rate_cents':-1}]:
        assert (await client.post('/api/v1/settings/venues',json={**body,**changes})).status_code==422
    assert (await client.post('/api/v1/settings/venues',json={**body,'provider_id':'missing'})).status_code==422
    with client.testing_session_factory() as db:
        db.get(ProviderConfig,pid).enabled=False;db.commit()
    assert (await client.post('/api/v1/settings/venues',json=body)).status_code==422
