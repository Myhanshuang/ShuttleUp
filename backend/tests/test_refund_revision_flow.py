import uuid

import httpx
import pytest

from shuttleup.app import app

pytestmark=pytest.mark.asyncio


async def identity(client,name):
    data=(await client.post('/api/v1/auth/guest',json={'display_name':name})).json();return data['user'],data['csrf_token']


async def test_settled_bill_refund_creates_reverse_transfer(client):
    host,hcsrf=await identity(client,'A');activity=(await client.post('/api/v1/activities',headers={'X-CSRF-Token':hcsrf},json={'title':'取消退款','min_players':2,'max_players':2})).json();aid=activity['id'];a=activity['my_participant_id']
    member=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver');_,mcsrf=await identity(member,'B');joined=(await member.post(f"/api/v1/invites/{activity['invite_token']}/join",json={})).json();b=joined['activity']['my_participant_id']
    current=(await client.get(f'/api/v1/activities/{aid}')).json();await client.post(f'/api/v1/activities/{aid}/cancel',headers={'X-CSRF-Token':hcsrf},json={'reason':'场馆关闭','expected_version':current['version']});await client.put(f'/api/v1/activities/{aid}/attendance',headers={'X-CSRF-Token':hcsrf},json={'entries':[{'participant_id':a,'state':'absent'},{'participant_id':b,'state':'absent'}],'verify':True})
    expense=(await client.post(f'/api/v1/activities/{aid}/expenses',headers={'X-CSRF-Token':hcsrf,'Idempotency-Key':str(uuid.uuid4())},json={'kind':'venue','description':'不可退场地费','amount_cents':12000,'payer_participant_id':a,'split_mode':'equal','split_scope':'selected','shares':[{'participant_id':a},{'participant_id':b}]})).json();current=(await client.get(f'/api/v1/activities/{aid}')).json();bill=(await client.post(f'/api/v1/activities/{aid}/bill/publish',headers={'X-CSRF-Token':hcsrf,'Idempotency-Key':str(uuid.uuid4())},json={'expected_generation':current['bill_generation']})).json();transfer=bill['snapshot']['transfers'][0]
    claim=(await member.post(f'/api/v1/activities/{aid}/payments',headers={'X-CSRF-Token':mcsrf,'Idempotency-Key':str(uuid.uuid4())},json={'bill_revision_id':bill['id'],'transfer_id':transfer['id'],'amount_cents':6000})).json();await client.post(f"/api/v1/activities/{aid}/payments/{claim['id']}/confirm",headers={'X-CSRF-Token':hcsrf,'Idempotency-Key':str(uuid.uuid4())})
    current=(await client.get(f'/api/v1/activities/{aid}')).json();await client.post(f'/api/v1/activities/{aid}/bill/reopen',headers={'X-CSRF-Token':hcsrf},json={'reason':'收到退款','expected_generation':current['bill_generation']});await client.post(f"/api/v1/activities/{aid}/expenses/{expense['id']}/refunds",headers={'X-CSRF-Token':hcsrf,'Idempotency-Key':str(uuid.uuid4())},json={'amount_cents':-4000,'payer_participant_id':a,'allocations':[]});current=(await client.get(f'/api/v1/activities/{aid}')).json();revised=(await client.post(f'/api/v1/activities/{aid}/bill/publish',headers={'X-CSRF-Token':hcsrf,'Idempotency-Key':str(uuid.uuid4())},json={'expected_generation':current['bill_generation']})).json();reverse=revised['snapshot']['transfers'][0]
    assert reverse['from_participant_id']==a and reverse['to_participant_id']==b and reverse['amount_cents']==2000
    await member.aclose()

