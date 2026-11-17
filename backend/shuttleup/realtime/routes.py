import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.service import current_user, require_user
from ..db import get_db, SessionLocal
from ..models import Event, Participant

router = APIRouter(tags=["realtime"])


@router.get("/events")
async def events(request: Request, watch_activity_id: str | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db)
    allowed = set(db.scalars(select(Participant.activity_id).where(Participant.user_id == user.id, Participant.membership == "active")).all())
    if watch_activity_id and watch_activity_id not in allowed:
        from fastapi import HTTPException
        raise HTTPException(403, detail={"code":"FORBIDDEN","message":"你不是这场活动的成员。"})
    try: cursor = int(request.headers.get("last-event-id") or db.scalar(select(func.max(Event.seq))) or 0)
    except ValueError: cursor = 0

    async def stream():
        nonlocal cursor
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        heartbeat = 0
        while True:
            if await request.is_disconnected(): break
            with SessionLocal() as session:
                authenticated = current_user(request, session)
                if not authenticated or authenticated.disabled_at:
                    break
                allowed = set(session.scalars(select(Participant.activity_id).where(Participant.user_id == user.id, Participant.membership == "active")).all())
                watched = {watch_activity_id} & allowed if watch_activity_id else allowed
                shared_users = set(session.scalars(select(Participant.user_id).where(Participant.activity_id.in_(watched), Participant.membership == "active")))
                rows = session.scalars(select(Event).where(Event.seq > cursor).order_by(Event.seq).limit(100)).all()
                for event in rows:
                    cursor = event.seq
                    time_change = event.type == "availability.changed" and event.owner_user_id in shared_users and (not event.payload.get("activity_ids") or bool(watched.intersection(event.payload["activity_ids"])))
                    if event.activity_id in watched or time_change or (not watch_activity_id and event.owner_user_id == user.id):
                        data = {"activity_id": event.activity_id, "resource": event.type.split('.')[0], "version": event.resource_version, "type": event.type, "actor_user_id": event.actor_user_id}
                        yield f"id: {event.seq}\nevent: resource.changed\ndata: {json.dumps(data)}\n\n"
            heartbeat += 1
            if heartbeat >= 15: yield ": keepalive\n\n"; heartbeat = 0
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
