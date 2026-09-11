import uuid

import pytest

pytestmark=pytest.mark.asyncio


async def test_cancelled_activity_no_cost_settles_and_archives(client):
    identity=(await client.post("/api/v1/auth/guest",json={"display_name":"主持人"})).json(); csrf=identity["csrf_token"]
    activity=(await client.post("/api/v1/activities",headers={"X-CSRF-Token":csrf},json={"title":"雨天取消"})).json()
    cancelled=await client.post(f"/api/v1/activities/{activity['id']}/cancel",headers={"X-CSRF-Token":csrf},json={"reason":"下雨","expected_version":activity["version"]})
    assert cancelled.status_code==200
    participant=(await client.get(f"/api/v1/activities/{activity['id']}/participants")).json()["items"][0]
    attendance=await client.put(f"/api/v1/activities/{activity['id']}/attendance",headers={"X-CSRF-Token":csrf},json={"entries":[{"participant_id":participant["id"],"state":"absent"}],"verify":True})
    generation=attendance.json()["bill_generation"]
    published=await client.post(f"/api/v1/activities/{activity['id']}/bill/publish",headers={"X-CSRF-Token":csrf,"Idempotency-Key":str(uuid.uuid4())},json={"expected_generation":generation})
    assert published.status_code==200 and published.json()["status"]=="settled"
    current=(await client.get(f"/api/v1/activities/{activity['id']}")).json()
    archived=await client.post(f"/api/v1/activities/{activity['id']}/archive",headers={"X-CSRF-Token":csrf},json={"expected_version":current["version"]})
    assert archived.status_code==200 and archived.json()["archived_at"]


async def test_expense_idempotency_does_not_duplicate(client):
    identity=(await client.post("/api/v1/auth/guest",json={"display_name":"A"})).json(); csrf=identity["csrf_token"]
    activity=(await client.post("/api/v1/activities",headers={"X-CSRF-Token":csrf},json={"title":"费用幂等"})).json(); participant=activity["my_participant_id"]
    key=str(uuid.uuid4()); payload={"kind":"extra","description":"测试","amount_cents":100,"payer_participant_id":participant,"split_mode":"equal","split_scope":"selected","shares":[{"participant_id":participant}]}
    one=await client.post(f"/api/v1/activities/{activity['id']}/expenses",headers={"X-CSRF-Token":csrf,"Idempotency-Key":key},json=payload)
    two=await client.post(f"/api/v1/activities/{activity['id']}/expenses",headers={"X-CSRF-Token":csrf,"Idempotency-Key":key},json=payload)
    assert one.status_code==201 and two.json()["id"]==one.json()["id"]
    assert len((await client.get(f"/api/v1/activities/{activity['id']}/expenses")).json()["items"])==1

