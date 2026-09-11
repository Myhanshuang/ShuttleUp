from fastapi import APIRouter,Depends,HTTPException,Request
from sqlalchemy import or_,select
from sqlalchemy.orm import Session

from ..activities.service import require_member
from ..auth.service import require_csrf,require_user
from ..common import from_ms
from ..db import get_db
from ..models import Activity,Event,Notification

router=APIRouter(tags=["notifications"])


@router.get("/notifications")
async def notifications(request: Request,unread: bool=False,db: Session=Depends(get_db)):
    user=require_user(request,db);query=select(Notification).where(Notification.target_user_id==user.id)
    if unread:query=query.where(Notification.read_at.is_(None))
    rows=db.scalars(query.order_by(Notification.available_at.desc()).limit(100)).all();return {"items":[{"id":n.id,"payload":n.payload,"state":n.state,"available_at":from_ms(n.available_at),"read_at":from_ms(n.read_at)} for n in rows],"next_cursor":None}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);row=db.get(Notification,notification_id)
    if not row or row.target_user_id!=user.id:raise HTTPException(404,detail={"code":"NOT_FOUND","message":"通知不存在。"})
    from ..models import now_ms
    row.read_at=now_ms();db.commit();return {"id":row.id,"read":True}


@router.get("/activities/{activity_id}/events")
async def activity_events(activity_id: str,request: Request,before: int|None=None,db: Session=Depends(get_db)):
    user=require_user(request,db);activity=db.get(Activity,activity_id);require_member(db,activity,user);query=select(Event).where(Event.activity_id==activity_id)
    if before is not None:query=query.where(Event.seq<before)
    rows=db.scalars(query.order_by(Event.seq.desc()).limit(50)).all();return {"items":[{"id":e.seq,"type":e.type,"actor_user_id":e.actor_user_id,"resource_version":e.resource_version,"payload":e.payload,"occurred_at":from_ms(e.occurred_at)} for e in rows],"next_cursor":rows[-1].seq if len(rows)==50 else None}

