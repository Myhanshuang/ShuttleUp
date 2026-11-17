import pytest
from sqlalchemy import select
from shuttleup.models import AvailabilityRule,Participant

@pytest.mark.asyncio
async def test_join_requires_valid_times_and_saves_atomically(client):
    host=(await client.post('/api/v1/auth/guest',json={'display_name':'主持人'})).json()
    activity=(await client.post('/api/v1/activities',json={'title':'加入测试'},headers={'X-CSRF-Token':host['csrf_token']})).json()
    client.cookies.clear()
    guest=(await client.post('/api/v1/auth/guest',json={'display_name':'新成员'})).json()
    headers={'X-CSRF-Token':guest['csrf_token']}
    url=f"/api/v1/invites/{activity['invite_token']}/join"
    assert (await client.post(url,json={},headers=headers)).status_code==422
    with client.testing_session_factory() as db:
        assert len(db.scalars(select(Participant)).all())==1
        assert not db.scalars(select(AvailabilityRule)).all()
    slot={'date':activity['date_from'],'start':'18:00','end':'20:00'}
    assert (await client.post(url,json={'availability':[{**slot,'end':'17:00'}]},headers=headers)).status_code==422
    assert (await client.post(url,json={'availability':[{**slot,'date':'2000-01-01'}]},headers=headers)).status_code==422
    r=await client.post(url,json={'availability':[slot]},headers=headers)
    assert r.status_code==200,r.text
    assert (await client.post(url,json={'availability':[slot]},headers=headers)).status_code==200
    with client.testing_session_factory() as db:
        rules=db.scalars(select(AvailabilityRule)).all()
        assert len(rules)==1 and rules[0].source=='activity' and rules[0].state=='free'
        assert rules[0].activity_id==activity['id'] and rules[0].user_id==guest['user']['id']
