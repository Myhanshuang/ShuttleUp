from fastapi import APIRouter,Depends,HTTPException,Request
from sqlalchemy import or_,select
from sqlalchemy.orm import Session

from ..activities.service import require_member
from ..auth.service import require_csrf,require_user
from ..common import from_ms
from ..db import get_db
from ..models import Activity,Event,Notification,Participant,User

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
    user=require_user(request,db);activity=db.get(Activity,activity_id);require_member(db,activity,user)
    member_ids=select(Participant.user_id).where(Participant.activity_id==activity_id,Participant.membership=="active")
    query=select(Event).where(or_(Event.activity_id==activity_id,
        (Event.type=="availability.changed") & Event.owner_user_id.in_(member_ids)))
    if before is not None:query=query.where(Event.seq<before)
    rows=db.scalars(query.order_by(Event.seq.desc()).limit(100)).all()
    visible=[e for e in rows if e.type!="availability.changed" or not e.payload.get("activity_ids") or activity_id in e.payload["activity_ids"]]
    names={u.id:u.display_name for u in db.scalars(select(User).where(User.id.in_([e.actor_user_id for e in visible if e.actor_user_id])))}
    return {"items":[{"id":e.seq,"type":e.type,"actor_user_id":e.actor_user_id,"actor_name":names.get(e.actor_user_id,"系统"),"resource_version":e.resource_version,"payload":{} if e.type=="availability.changed" else e.payload,"occurred_at":from_ms(e.occurred_at)} for e in visible],"next_cursor":rows[-1].seq if len(rows)==100 else None}
