import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.service import require_user
from ..db import get_db, SessionLocal
from ..models import Event, Participant

router = APIRouter(tags=["realtime"])


@router.get("/events")
async def events(request: Request, watch_activity_id: str | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db)
    allowed = set(db.scalars(select(Participant.activity_id).where(Participant.user_id == user.id, Participant.membership == "active")).all())
    cursor = int(request.headers.get("last-event-id", "0") or 0)

    async def stream():
        nonlocal cursor
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        heartbeat = 0
        while True:
            if await request.is_disconnected(): break
            with SessionLocal() as session:
                rows = session.scalars(select(Event).where(Event.seq > cursor).order_by(Event.seq).limit(100)).all()
                for event in rows:
                    cursor = event.seq
                    if event.owner_user_id == user.id or event.activity_id in allowed:
                        data = {"activity_id": event.activity_id, "resource": event.type.split('.')[0], "version": event.resource_version}
                        yield f"id: {event.seq}\nevent: resource.changed\ndata: {json.dumps(data)}\n\n"
            heartbeat += 1
            if heartbeat >= 15: yield ": keepalive\n\n"; heartbeat = 0
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

