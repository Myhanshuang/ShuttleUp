from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth.service import require_csrf, require_user
from ..common import short_code, to_ms
from ..db import get_db
from ..models import Activity, ActivityPlan, AvailabilityRule, Booking, Expense, OperationKey, Participant, Venue, now_ms
from ..venues.routes import compute_candidates
from ..billing.routes import idempotent
from .service import activity_dto, emit, participant_for, require_host, require_member

router = APIRouter(tags=["activity-workflow"])


class SelectPlan(BaseModel):
    candidate_id: str
    roster_participant_ids: list[str] = Field(min_length=2, max_length=30)
    expected_version: int


class BookingCreate(BaseModel):
    venue_id: str
    court_ids: list[str] = Field(min_length=1, max_length=8)
    starts_at: datetime
    ends_at: datetime
    external_order_no: str | None = Field(default=None, max_length=120)
    booker_participant_id: str
    quoted_total_cents: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=240)
    expected_version: int


class BookingPayment(BaseModel): amount_cents: int = Field(gt=0, le=100_000_000); payer_participant_id: str
class BookingCancel(BaseModel): reason: str=Field(min_length=1,max_length=240); expected_version: int
class VersionRequest(BaseModel): expected_version: int
class CancelRequest(VersionRequest): reason: str = Field(min_length=1, max_length=240)
class RsvpRequest(BaseModel): plan_id: str; response: str = Field(pattern="^(yes|no)$")
class AttendanceEntry(BaseModel): participant_id: str; state: str = Field(pattern="^(present|absent)$")
class AttendanceRequest(BaseModel): entries: list[AttendanceEntry] = Field(min_length=1, max_length=30); verify: bool = False


def check_version(activity: Activity, expected: int):
    if activity.version != expected: raise HTTPException(409, detail={"code":"VERSION_CONFLICT","message":"活动刚刚有更新。","current_version":activity.version})


def plan_dto(plan: ActivityPlan): return {"id":plan.id,"plan_no":plan.plan_no,"starts_at":datetime.fromtimestamp(plan.starts_at/1000,timezone.utc).isoformat(),"ends_at":datetime.fromtimestamp(plan.ends_at/1000,timezone.utc).isoformat(),"venue_id":plan.venue_id,"court_ids":plan.court_ids,"roster_participant_ids":plan.roster_participant_ids,"snapshot":plan.snapshot}


def booking_dto(b: Booking): return {"id":b.id,"plan_id":b.plan_id,"venue_id":b.venue_id,"court_ids":b.court_ids,"starts_at":datetime.fromtimestamp(b.starts_at/1000,timezone.utc).isoformat(),"ends_at":datetime.fromtimestamp(b.ends_at/1000,timezone.utc).isoformat(),"external_order_no":b.external_order_no,"booker_participant_id":b.booker_participant_id,"status":b.status,"quoted_total_cents":b.quoted_total_cents,"paid_total_cents":b.paid_total_cents,"note":b.note}


def coverage_count(bookings: list[Booking], plan: ActivityPlan) -> int:
    by_court={}
    for booking in bookings:
        if booking.status!="confirmed" or booking.venue_id!=plan.venue_id: continue
        for court in booking.court_ids: by_court.setdefault(court,[]).append((booking.starts_at,booking.ends_at))
    covered=0
    for intervals in by_court.values():
        cursor=plan.starts_at
        for start,end in sorted(intervals):
            if start>cursor: break
            if start<=cursor<end: cursor=max(cursor,end)
        if cursor>=plan.ends_at: covered+=1
    return covered


@router.post("/activities/{activity_id}/plans", status_code=201)
async def select_plan(activity_id: str, body: SelectPlan, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user); check_version(activity,body.expected_version)
    if activity.status not in ("collecting","booking"): raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"当前状态不能选择方案。"})
    candidate=next((c for c in compute_candidates(db,activity,100)["candidates"] if c["id"]==body.candidate_id),None)
    if not candidate: raise HTTPException(409,detail={"code":"CANDIDATE_CHANGED","message":"方案已变化，请重新选择。"})
    roster=list(dict.fromkeys(body.roster_participant_ids))
    if not activity.min_players<=len(roster)<=activity.max_players: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"拟参加人数不符合活动设置。"})
    ps=db.scalars(select(Participant).where(Participant.activity_id==activity_id,Participant.membership=="active")).all(); known={p.id for p in ps}; required={p.id for p in ps if p.required}
    if not set(roster)<=known or not required<=set(roster) or not set(roster)<=set(candidate["eligible_participant_ids"]): raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"名单必须来自全程有空成员并包含所有核心成员。"})
    number=(db.scalar(select(func.max(ActivityPlan.plan_no)).where(ActivityPlan.activity_id==activity_id)) or 0)+1
    plan=ActivityPlan(activity_id=activity_id,plan_no=number,starts_at=int(datetime.fromisoformat(candidate["starts_at"]).timestamp()*1000),ends_at=int(datetime.fromisoformat(candidate["ends_at"]).timestamp()*1000),venue_id=candidate["venue_id"],court_ids=candidate["court_ids"],roster_participant_ids=roster,candidate_fingerprint=candidate["fingerprint"],snapshot=candidate,selected_by=user.id)
    db.add(plan); db.flush(); db.execute(delete(AvailabilityRule).where(AvailabilityRule.activity_id==activity_id,AvailabilityRule.origin_plan_id.is_not(None)))
    for p in ps: p.rsvp="pending"; p.rsvp_plan_id=plan.id if p.id in roster else None
    activity.current_plan_id=plan.id; activity.status="booking"; activity.version+=1; emit(db,"plan.selected",activity=activity,actor=user,payload={"plan_id":plan.id,"plan_no":number}); db.commit(); return plan_dto(plan)


@router.delete("/activities/{activity_id}/plan",status_code=204)
async def clear_plan(activity_id: str,expected_version: int,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);require_member(db,activity,user);require_host(activity,user);check_version(activity,expected_version)
    if activity.status!="booking" or not activity.current_plan_id: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"当前没有可清除的待订方案。"})
    if db.scalar(select(Booking.id).where(Booking.plan_id==activity.current_plan_id,Booking.status=="confirmed")): raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"已有有效订单，请先走改约流程处理订单。"})
    db.execute(delete(AvailabilityRule).where(AvailabilityRule.activity_id==activity_id,AvailabilityRule.origin_plan_id==activity.current_plan_id))
    for p in db.scalars(select(Participant).where(Participant.activity_id==activity_id)).all():p.rsvp="pending";p.rsvp_plan_id=None
    activity.current_plan_id=None;activity.status="collecting";activity.version+=1;emit(db,"activity.updated",activity=activity,actor=user,payload={"plan_cleared":True});db.commit()


@router.put("/activities/{activity_id}/rsvp")
async def rsvp(activity_id: str, body: RsvpRequest, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); p=require_member(db,activity,user)
    if activity.current_plan_id!=body.plan_id or p.rsvp_plan_id!=body.plan_id: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"你不在当前拟参加名单中。"})
    plan=db.get(ActivityPlan,body.plan_id); db.execute(delete(AvailabilityRule).where(AvailabilityRule.user_id==user.id,AvailabilityRule.activity_id==activity_id,AvailabilityRule.origin_plan_id==body.plan_id))
    p.rsvp=body.response
    if body.response=="yes":
        user.availability_revision+=1; db.add(AvailabilityRule(user_id=user.id,activity_id=activity_id,origin_plan_id=plan.id,source="activity",state="free",kind="once",start_at=plan.starts_at,end_at=plan.ends_at,edit_seq=user.availability_revision))
    activity.version+=1; emit(db,"rsvp.changed",activity=activity,actor=user,payload={"participant_id":p.id,"response":body.response}); db.commit(); return {"participant_id":p.id,"rsvp":p.rsvp,"plan_id":plan.id}


@router.get("/activities/{activity_id}/bookings")
async def bookings(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db); activity=db.get(Activity,activity_id); require_member(db,activity,user); items=db.scalars(select(Booking).where(Booking.activity_id==activity_id)).all(); return {"items":[booking_dto(b) for b in items],"next_cursor":None}


@router.post("/activities/{activity_id}/bookings", status_code=201)
async def record_booking(activity_id: str, body: BookingCreate, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user); check_version(activity,body.expected_version)
    if activity.status not in ("booking","confirmed") or not activity.current_plan_id: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"请先选择方案。"})
    plan=db.get(ActivityPlan,activity.current_plan_id)
    if body.ends_at<=body.starts_at or body.venue_id!=plan.venue_id: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"订单必须对应当前方案场馆和有效时段。"})
    participant=db.get(Participant,body.booker_participant_id)
    if not participant or participant.activity_id!=activity_id: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"订场人不属于本活动。"})
    booking=Booking(activity_id=activity_id,plan_id=plan.id,venue_id=body.venue_id,court_ids=body.court_ids,starts_at=to_ms(body.starts_at),ends_at=to_ms(body.ends_at),external_order_no=body.external_order_no,booker_participant_id=body.booker_participant_id,quoted_total_cents=body.quoted_total_cents,note=body.note)
    db.add(booking); db.flush(); active=db.scalars(select(Booking).where(Booking.activity_id==activity_id,Booking.plan_id==plan.id)).all(); confirmed=coverage_count(active,plan)>=activity.court_count
    activity.status="confirmed" if confirmed else "booking"; activity.version+=1; emit(db,"booking.confirmed" if confirmed else "booking.recorded",activity=activity,actor=user,payload={"booking_id":booking.id}); db.commit(); return {**booking_dto(booking),"activity_status":activity.status}


@router.post("/activities/{activity_id}/bookings/{booking_id}/payment", status_code=201)
async def booking_payment(activity_id: str, booking_id: str, body: BookingPayment, request: Request, idempotency_key: str | None=Header(default=None), db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user); booking=db.get(Booking,booking_id)
    if not booking or booking.activity_id!=activity_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"订单不存在。"})
    payer=db.get(Participant,body.payer_participant_id)
    if not payer or payer.activity_id!=activity_id: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"垫付人不属于本活动。"})
    old,digest=idempotent(db,f"{user.id}:booking.payment:{booking_id}",idempotency_key,body.model_dump())
    if old:return old.response
    expense=Expense(short_code=short_code(),activity_id=activity_id,kind="venue",description="场地费",amount_cents=body.amount_cents,payer_participant_id=payer.id,split_mode="equal",split_scope="attendees",booking_id=booking.id,created_by=user.id)
    db.add(expense); db.flush(); booking.paid_total_cents+=body.amount_cents; booking.payer_participant_id=payer.id; activity.bill_generation+=1; activity.version+=1; emit(db,"expense.created",activity=activity,actor=user,payload={"expense_id":expense.id,"booking_id":booking.id})
    result={"booking_id":booking.id,"expense_id":expense.id,"paid_total_cents":booking.paid_total_cents}; db.add(OperationKey(scope=f"{user.id}:booking.payment:{booking_id}",key=idempotency_key,request_hash=digest,response_status=201,response=result,expires_at=now_ms()+30*86400000)); db.commit(); return result


@router.post("/activities/{activity_id}/bookings/{booking_id}/cancel")
async def cancel_booking(activity_id: str,booking_id: str,body: BookingCancel,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);require_member(db,activity,user);require_host(activity,user);check_version(activity,body.expected_version);booking=db.get(Booking,booking_id)
    if not booking or booking.activity_id!=activity_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"订单不存在。"})
    if booking.status!="confirmed": raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"订单已经取消。"})
    booking.status="cancelled";booking.note=((booking.note+" · ") if booking.note else "")+f"取消原因：{body.reason}";plan=db.get(ActivityPlan,activity.current_plan_id) if activity.current_plan_id else None
    activity.status="confirmed" if plan and coverage_count(db.scalars(select(Booking).where(Booking.plan_id==plan.id)).all(),plan)>=activity.court_count else "booking";activity.version+=1;emit(db,"booking.cancelled",activity=activity,actor=user,payload={"booking_id":booking.id,"reason":body.reason});db.commit();return {**booking_dto(booking),"activity_status":activity.status,"version":activity.version}


@router.put("/activities/{activity_id}/attendance")
async def attendance(activity_id: str, body: AttendanceRequest, request: Request, db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); mine=require_member(db,activity,user); is_host=activity.host_user_id==user.id
    for entry in body.entries:
        p=db.get(Participant,entry.participant_id)
        if not p or p.activity_id!=activity_id: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"成员不属于本活动。"})
        if p.id!=mine.id and not is_host: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"普通成员只能更新自己的到场状态。"})
        p.attendance=entry.state; p.attendance_verified=bool(body.verify and is_host) or p.attendance_verified
    activity.bill_generation+=1; activity.version+=1; emit(db,"attendance.changed",activity=activity,actor=user); db.commit(); return {"bill_generation":activity.bill_generation,"version":activity.version}


@router.post("/activities/{activity_id}/finish")
async def finish(activity_id: str, body: VersionRequest, request: Request, db: Session=Depends(get_db)):
    return transition(activity_id,body.expected_version,"finished",request,db)


@router.post("/activities/{activity_id}/cancel")
async def cancel(activity_id: str, body: CancelRequest, request: Request, db: Session=Depends(get_db)):
    return transition(activity_id,body.expected_version,"cancelled",request,db,body.reason)


def transition(activity_id,expected,target,request,db,reason=None):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user); check_version(activity,expected)
    allowed={"finished":{"confirmed"},"cancelled":{"collecting","booking","confirmed"}}
    if activity.status not in allowed[target]: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"当前状态不能执行此操作。"})
    activity.status=target; activity.cancel_reason=reason; activity.version+=1; emit(db,f"activity.{target}",activity=activity,actor=user,payload={"reason":reason} if reason else {}); db.commit(); return activity_dto(db,activity,user)


@router.post("/activities/{activity_id}/archive")
async def archive(activity_id: str, body: VersionRequest, request: Request, db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user); check_version(activity,body.expected_version)
    if activity.status not in ("finished","cancelled") or activity.billing_status!="settled": raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"活动结束且账单结清后才能归档。"})
    activity.archived_at=now_ms(); activity.version+=1; emit(db,"activity.archived",activity=activity,actor=user); db.commit(); return activity_dto(db,activity,user)
