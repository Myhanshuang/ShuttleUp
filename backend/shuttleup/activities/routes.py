from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.service import create_session, current_user, require_csrf, require_user
from ..common import short_code, to_ms
from ..db import get_db
from ..models import Activity, ActivityPlan, Venue, ProviderConfig, AppSetting, Participant, User, AvailabilityRule
from ..security import invite_token, token, token_hash
from .schemas import ActivityCreate, ActivityPatch, CloneRequest, HostTransfer, InviteAction, JoinRequest, OfflineParticipant, ParticipantPatch
from .service import activity_dto, emit, participant_for, require_host, require_member

router = APIRouter(tags=["activities"])


def unique_code(db: Session) -> str:
    while True:
        value = short_code()
        if not db.scalar(select(Activity.id).where(Activity.short_code == value)):
            return value


@router.get("/activities")
async def list_activities(request: Request, scope: str = "active", db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = select(Activity).join(Participant).where(Participant.user_id == user.id)
    if scope != "history": query = query.where(Activity.archived_at.is_(None))
    else: query = query.where(Activity.archived_at.is_not(None))
    items = [activity_dto(db, a, user) for a in db.scalars(query.order_by(Activity.updated_at.desc())).all()]
    return {"items": items, "next_cursor": None}


def validate_venues(db, ids):
    if len(ids) != len(set(ids)):
        raise HTTPException(422, detail={"code":"VALIDATION_ERROR","message":"场馆不能重复。"})
    for vid in ids:
        venue=db.get(Venue,vid)
        provider=db.get(ProviderConfig,venue.provider_id) if venue else None
        if not venue or not venue.enabled or not provider or not provider.enabled:
            raise HTTPException(422, detail={"code":"VALIDATION_ERROR","message":"所选场馆不存在或已停用。"})


@router.post("/activities", status_code=201)
async def create_activity(body: ActivityCreate, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request)
    validate_venues(db, body.venue_preferences)
    settings = db.get(AppSetting, 1)
    activity_id = __import__("uuid").uuid4().__str__()
    nonce = token(16); raw_invite = invite_token(activity_id, nonce)
    prices = {
        "global_court_hourly_cents": settings.court_hourly_cents if settings else None,
        "venue_hourly_cents": {},
        "court_hourly_override_cents": body.price_overrides.get("court_hourly_cents"),
        "shuttle_unit_cents": body.price_overrides.get("shuttle_unit_cents", settings.shuttle_unit_cents if settings else None),
        "shuttle_label": settings.shuttle_label if settings else None,
    }
    activity = Activity(id=activity_id, short_code=unique_code(db), title=body.title.strip(), host_user_id=user.id,
        timezone=body.timezone, date_from=body.date_from.isoformat(), date_to=body.date_to.isoformat(),
        daily_windows=[w.model_dump() for w in body.daily_windows], duration_minutes=body.duration_minutes,
        min_players=body.min_players, max_players=body.max_players, court_count=body.court_count,
        venue_preferences=body.venue_preferences, decision_deadline=to_ms(body.decision_deadline),
        invite_nonce=nonce, invite_token_hash=token_hash(raw_invite), price_defaults=prices)
    db.add(activity); db.flush()
    db.add(Participant(activity_id=activity.id, user_id=user.id, display_name=user.display_name, join_order=1, required=True))
    emit(db, "activity.created", activity=activity, actor=user)
    db.commit()
    return {**activity_dto(db, activity, user), "invite_token": raw_invite, "invite_url": f"/i/{raw_invite}"}


@router.get("/activities/{activity_id}")
async def get_activity(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    return activity_dto(db, activity, user)


@router.patch("/activities/{activity_id}")
async def patch_activity(activity_id: str, body: ActivityPatch, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id)
    require_member(db, activity, user); require_host(activity, user)
    if activity.version != body.expected_version:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "活动刚刚有更新。", "current_version": activity.version})
    timing={key:getattr(body,key) for key in ("duration_minutes","date_from","date_to","daily_windows") if getattr(body,key) is not None}
    if timing:
        if activity.status != "collecting":
            raise HTTPException(409, detail={"code":"INVALID_TRANSITION","message":"请先处理已有订场并清除方案，再调整活动时间。"})
        from pydantic import ValidationError
        try:
            validated=ActivityCreate.model_validate({"title":activity.title,"date_from":activity.date_from,
                "date_to":activity.date_to,"duration_minutes":activity.duration_minutes,"daily_windows":activity.daily_windows,
                **{k:([w.model_dump() for w in v] if k=="daily_windows" else v) for k,v in timing.items()}})
        except ValidationError:
            raise HTTPException(422, detail={"code":"VALIDATION_ERROR","message":"请检查日期范围（最多14天）、每日开始和结束时间。"}) from None
        activity.date_from=validated.date_from.isoformat();activity.date_to=validated.date_to.isoformat()
        activity.duration_minutes=validated.duration_minutes
        activity.daily_windows=[w.model_dump() for w in validated.daily_windows]
    if body.venue_preferences is not None:
        if activity.status != "collecting":
            raise HTTPException(409, detail={"code":"INVALID_TRANSITION","message":"请先清除待订方案，再修改场馆。"})
        validate_venues(db,body.venue_preferences)
        activity.venue_preferences=body.venue_preferences
    if body.title is not None: activity.title = body.title.strip()
    if "decision_deadline" in body.model_fields_set: activity.decision_deadline = to_ms(body.decision_deadline)
    activity.version += 1; emit(db, "activity.updated", activity=activity, actor=user); db.commit()
    return activity_dto(db, activity, user)


@router.get("/activities/{activity_id}/participants")
async def participants(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    items = db.scalars(select(Participant).where(Participant.activity_id == activity_id).order_by(Participant.join_order)).all()
    return {"items": [{"id": p.id, "user_id": p.user_id, "display_name": p.display_name, "join_order": p.join_order, "membership": p.membership, "required": p.required, "rsvp": p.rsvp, "attendance": p.attendance, "attendance_verified": p.attendance_verified} for p in items], "next_cursor": None}


@router.get("/activities/{activity_id}/invite")
async def get_invite(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user); require_host(activity, user)
    raw = invite_token(activity.id, activity.invite_nonce)
    return {"token": raw, "url": f"/i/{raw}", "enabled": activity.invite_enabled}


@router.post("/activities/{activity_id}/invite")
async def manage_invite(activity_id: str, body: InviteAction, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user); require_host(activity,user)
    if activity.version!=body.expected_version: raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"活动刚刚有更新。","current_version":activity.version})
    if body.action=="rotate":
        activity.invite_nonce=token(16); raw=invite_token(activity.id,activity.invite_nonce); activity.invite_token_hash=token_hash(raw); activity.invite_enabled=True
    else: activity.invite_enabled=False; raw=None
    activity.version+=1; emit(db,"activity.updated",activity=activity,actor=user,payload={"invite_action":body.action}); db.commit(); return {"enabled":activity.invite_enabled,"token":raw,"url":f"/i/{raw}" if raw else None,"version":activity.version}


@router.post("/activities/{activity_id}/clone",status_code=201)
async def clone_activity(activity_id: str, body: CloneRequest, request: Request, db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); source=db.get(Activity,activity_id); require_member(db,source,user)
    create=ActivityCreate(title=body.title,date_from=body.date_from,date_to=body.date_to,timezone=source.timezone,daily_windows=source.daily_windows,duration_minutes=source.duration_minutes,min_players=source.min_players,max_players=source.max_players,court_count=source.court_count,venue_preferences=source.venue_preferences,price_overrides={"court_hourly_cents":source.price_defaults.get("court_hourly_override_cents"),"shuttle_unit_cents":source.price_defaults.get("shuttle_unit_cents")})
    activity_id_new=str(__import__("uuid").uuid4()); nonce=token(16); raw=invite_token(activity_id_new,nonce)
    activity=Activity(id=activity_id_new,short_code=unique_code(db),title=create.title,host_user_id=user.id,status="collecting",timezone=create.timezone,date_from=create.date_from.isoformat(),date_to=create.date_to.isoformat(),daily_windows=[w.model_dump() for w in create.daily_windows],duration_minutes=create.duration_minutes,min_players=create.min_players,max_players=create.max_players,court_count=create.court_count,venue_preferences=create.venue_preferences,invite_nonce=nonce,invite_token_hash=token_hash(raw),price_defaults=source.price_defaults.copy())
    db.add(activity);db.flush();db.add(Participant(activity_id=activity.id,user_id=user.id,display_name=user.display_name,join_order=1,required=True));emit(db,"activity.created",activity=activity,actor=user,payload={"cloned_from":source.id});db.commit();return {**activity_dto(db,activity,user),"invite_token":raw,"invite_url":f"/i/{raw}"}


@router.get("/invites/{raw_token}")
async def invite_summary(raw_token: str, db: Session = Depends(get_db)):
    activity = db.scalar(select(Activity).where(Activity.invite_token_hash == token_hash(raw_token), Activity.invite_enabled.is_(True)))
    if not activity: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "邀请链接无效或已关闭。"})
    host = db.get(User, activity.host_user_id)
    count = db.scalar(select(func.count()).select_from(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active"))
    return {"title": activity.title, "host_name": host.display_name, "date_from": activity.date_from, "date_to": activity.date_to, "status": activity.status, "participant_count": count, "min_players": activity.min_players, "max_players": activity.max_players}


@router.post("/invites/{raw_token}/join")
async def join(raw_token: str, body: JoinRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    activity = db.scalar(select(Activity).where(Activity.invite_token_hash == token_hash(raw_token), Activity.invite_enabled.is_(True)))
    if not activity: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "邀请链接无效或已关闭。"})
    user = current_user(request, db); csrf = None
    existing = participant_for(db, activity.id, user.id, include_inactive=True) if user else None
    if existing and existing.membership == "removed":
        raise HTTPException(403, detail={"code": "MEMBER_REMOVED", "message": "你已被移出本活动，请联系主持人恢复成员身份。"})
    joining = not existing or existing.membership != "active"
    if joining:
        if activity.status not in ("collecting", "booking", "confirmed"):
            raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "活动已结束或取消，不能加入。"})
        if not body.availability:
            raise HTTPException(422, detail={"code": "AVAILABILITY_REQUIRED", "message": "请先填写至少一段本次活动的空闲时间，再加入活动。"})
        if any(not activity.date_from <= item.date.isoformat() <= activity.date_to for item in body.availability):
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "空闲日期必须在本次活动的日期范围内。"})
    if not user:
        if not body.display_name: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "请输入昵称。"})
        user = User(display_name=body.display_name.strip()); db.add(user); db.flush(); csrf = create_session(db, response, user)
    existing = participant_for(db, activity.id, user.id, include_inactive=True)
    if not existing:
        order = (db.scalar(select(func.max(Participant.join_order)).where(Participant.activity_id == activity.id)) or 0) + 1
        db.add(Participant(activity_id=activity.id, user_id=user.id, display_name=user.display_name, join_order=order))
        activity.version += 1; emit(db, "participant.joined", activity=activity, actor=user)
    elif existing.membership == "removed":
        raise HTTPException(403, detail={"code": "MEMBER_REMOVED", "message": "你已被移出本活动，请联系主持人恢复成员身份。"})
    elif existing.membership != "active":
        existing.membership = "active"; activity.version += 1; emit(db, "participant.joined", activity=activity, actor=user)
    if joining:
        user.availability_revision += 1
        for item in body.availability:
            begin = datetime.fromisoformat(f"{item.date}T{item.start}").replace(tzinfo=ZoneInfo(activity.timezone))
            end = datetime.fromisoformat(f"{item.date}T{item.end}").replace(tzinfo=ZoneInfo(activity.timezone))
            db.add(AvailabilityRule(user_id=user.id, activity_id=activity.id, source="activity", state="free", kind="once",
                start_at=to_ms(begin), end_at=to_ms(end), edit_seq=user.availability_revision))
        emit(db, "availability.changed", activity=activity, actor=user, owner_user_id=user.id, payload={"revision": user.availability_revision})
    db.commit()
    return {"activity": activity_dto(db, activity, user), "user": {"id": user.id, "display_name": user.display_name}, "csrf_token": csrf}


@router.post("/activities/{activity_id}/leave")
async def leave(activity_id: str,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);p=require_member(db,activity,user)
    if activity.host_user_id==user.id: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"主持人需先转交主持人身份。"})
    p.membership="left";activity.version+=1;emit(db,"participant.left",activity=activity,actor=user,payload={"participant_id":p.id});db.commit();return {"membership":"left","version":activity.version}


@router.post("/activities/{activity_id}/host")
async def transfer_host(activity_id: str,body: HostTransfer,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);require_member(db,activity,user);require_host(activity,user)
    if activity.version!=body.expected_version: raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"活动刚刚有更新。","current_version":activity.version})
    target=participant_for(db,activity_id,body.new_host_user_id)
    if not target: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"新主持人必须是当前成员。"})
    activity.host_user_id=target.user_id;activity.version+=1;emit(db,"activity.updated",activity=activity,actor=user,payload={"host_user_id":target.user_id});db.commit();return activity_dto(db,activity,user)


@router.post("/activities/{activity_id}/participants/offline",status_code=201)
async def add_offline(activity_id: str,body: OfflineParticipant,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);require_member(db,activity,user);require_host(activity,user)
    guest=User(display_name=body.display_name);db.add(guest);db.flush();order=(db.scalar(select(func.max(Participant.join_order)).where(Participant.activity_id==activity_id)) or 0)+1;p=Participant(activity_id=activity_id,user_id=guest.id,display_name=guest.display_name,join_order=order);db.add(p);activity.version+=1;emit(db,"participant.joined",activity=activity,actor=user,payload={"participant_id":p.id,"offline":True});db.commit();return {"id":p.id,"user_id":guest.id,"display_name":p.display_name,"join_order":p.join_order}


@router.patch("/activities/{activity_id}/participants/{participant_id}")
async def patch_participant(activity_id: str,participant_id: str,body: ParticipantPatch,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);activity=db.get(Activity,activity_id);
    if not activity: raise HTTPException(404, detail={"code":"NOT_FOUND","message":"活动不存在。"})
    if not user.is_admin:
        require_member(db,activity,user);require_host(activity,user)
    if activity.version!=body.expected_version: raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"活动刚刚有更新。","current_version":activity.version})
    p=db.get(Participant,participant_id)
    if not p or p.activity_id!=activity_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"成员不存在。"})
    if body.membership=="removed" and p.user_id==activity.host_user_id: raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"不能移除当前主持人。"})
    if activity.status in ("finished", "cancelled"):
        raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"活动已结束，保留成员记录用于结算。"})
    if body.membership == "removed" and p.membership == "active" and activity.current_plan_id:
        plan=db.get(ActivityPlan,activity.current_plan_id)
        if plan and p.id in plan.roster_participant_ids:
            raise HTTPException(409,detail={"code":"MEMBER_IN_PLAN","message":"成员已在当前方案名单中，请先调整或清除方案。"})
    if body.required is not None:p.required=body.required
    if body.membership is not None:p.membership=body.membership
    activity.version+=1;emit(db,"participant.updated",activity=activity,actor=user,payload={"participant_id":p.id});db.commit();return {"id":p.id,"membership":p.membership,"required":p.required,"version":activity.version}
