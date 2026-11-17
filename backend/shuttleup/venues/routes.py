import asyncio
import time as monotonic_time
from collections import Counter
import hashlib
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..activities.service import emit, require_member
from ..auth.service import require_csrf, require_user
from ..common import from_ms
from ..db import get_db
from ..models import Activity, AvailabilityRule, Participant, ProviderConfig, User, Venue, VenueSnapshot, now_ms
from ..availability.engine import Interval, Rule, resolve_availability, summarize_window
from .candidates import generate_candidates
from .providers import VenueDayResult, supported_provider
from .service import refresh_day, get_snapshot
from zoneinfo import ZoneInfo
from . import login
from .local import extension_for

router = APIRouter(tags=["venues"])


class ProviderCreate(BaseModel):
    key: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_-]+$")
    adapter_key: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=80)
    config: dict = Field(default_factory=dict)
    credential_env: str | None = Field(default=None, pattern=r"^VENUE_[A-Z0-9_]+$")
    min_poll_seconds: int = Field(default=30, ge=10)
    min_request_interval_seconds: int = Field(default=2, ge=1)
    fresh_for_seconds: int = Field(default=90, ge=10)


class VenueDetails(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(default="", max_length=240)
    booking_url: str = Field(default="", max_length=2048)
    hourly_rate_cents: int | None = Field(default=None, ge=0, le=100_000_000)

    @field_validator("booking_url")
    @classmethod
    def valid_booking_url(cls, value):
        return str(HttpUrl(value)) if value else ""


class VenueCreate(VenueDetails):
    provider_id: str = Field(min_length=1, max_length=36)
    external_venue_id: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError):
            raise ValueError("无效的时区")
        return value


class VenueUpdate(VenueDetails):
    enabled: bool
    expected_version: int = Field(ge=1)


def venue_dto(v):
    return {key: getattr(v, key) for key in ("id", "provider_id", "external_venue_id",
        "name", "address", "timezone", "booking_url", "hourly_rate_cents", "enabled", "version")}


def admin(request: Request, db: Session, write: bool=True) -> User:
    user = require_user(request, db)
    if write: require_csrf(request)
    if not user.is_admin: raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "只有实例管理员可以修改场馆来源。"})
    return user


@router.get("/venues")
async def venues(request: Request, db: Session = Depends(get_db)):
    require_user(request, db); items = db.scalars(select(Venue).where(Venue.enabled.is_(True))).all()
    return {"items": [{"id": v.id, "name": v.name, "address": v.address, "booking_url": v.booking_url, "hourly_rate_cents": v.hourly_rate_cents, "provider_id": v.provider_id} for v in items], "next_cursor": None}


@router.post("/settings/providers", status_code=201)
async def create_provider(body: ProviderCreate, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    if not supported_provider(body.adapter_key):
        raise HTTPException(422, detail={"code": "ADAPTER_UNAVAILABLE", "message": "本机没有安装该来源扩展。"})
    model = ProviderConfig(**body.model_dump()); db.add(model); db.commit(); return {"id": model.id, **body.model_dump()}


@router.get("/settings/providers")
async def list_providers(request: Request,db: Session=Depends(get_db)):
    admin(request,db,False);items=db.scalars(select(ProviderConfig).order_by(ProviderConfig.label)).all();return {"items":[{"id":p.id,"key":p.key,"adapter_key":p.adapter_key,"label":p.label,"min_poll_seconds":p.min_poll_seconds,"min_request_interval_seconds":p.min_request_interval_seconds,"fresh_for_seconds":p.fresh_for_seconds,"enabled":p.enabled,"credential_env":p.credential_env,"config":p.config,"version":p.version} for p in items],"next_cursor":None}


@router.get("/settings/venue-sources")
async def venue_sources(request: Request, db: Session = Depends(get_db)):
    admin(request, db, False)
    return {"items": [{"id": p.id, "label": p.label, "enabled": p.enabled,
        "manual": p.adapter_key == "manual"} for p in db.scalars(select(ProviderConfig).order_by(ProviderConfig.label))]}


@router.get("/settings/venues")
async def admin_venues(request: Request, db: Session = Depends(get_db)):
    admin(request, db, False)
    return {"items": [venue_dto(v) for v in db.scalars(select(Venue).order_by(Venue.name))]}


@router.post("/settings/venues", status_code=201)
async def create_venue(body: VenueCreate, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    provider = db.get(ProviderConfig, body.provider_id)
    if not provider or not provider.enabled:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "请选择已启用的场馆来源。"})
    model = Venue(**body.model_dump())
    db.add(model)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": "VENUE_EXISTS", "message": "该来源下的场馆编号已存在，请编辑已有场馆。"}) from None
    return venue_dto(model)


@router.put("/settings/venues/{venue_id}")
async def update_venue(venue_id: str, body: VenueUpdate, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    venue = db.get(Venue, venue_id)
    if not venue:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "场馆不存在。"})
    result = db.execute(update(Venue).where(Venue.id == venue_id, Venue.version == body.expected_version)
        .values(**body.model_dump(exclude={"expected_version"}), version=Venue.version + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "场馆信息已更新，请重新载入后再修改。"})
    db.commit()
    db.refresh(venue)
    return venue_dto(venue)


@router.put("/settings/venues/{venue_id}/manual-slots")
async def manual_slots(venue_id: str, body: VenueDayResult, request: Request, db: Session = Depends(get_db)):
    user = admin(request, db); venue = db.get(Venue, venue_id)
    if not venue or venue.external_venue_id != body.external_venue_id: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "场馆与数据不匹配。"})
    provider = db.get(ProviderConfig, venue.provider_id)
    if provider.adapter_key != "manual": raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "只有人工来源可直接编辑余量。"})
    content = {"coverage": body.coverage.model_dump(mode="json"), "slots": [s.model_dump(mode="json") for s in body.slots]}; digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(); now = now_ms()
    snapshot = db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id == venue_id, VenueSnapshot.local_date == body.local_date.isoformat()))
    changed = not snapshot or snapshot.content_hash != digest
    if not snapshot: snapshot = VenueSnapshot(venue_id=venue_id, local_date=body.local_date.isoformat(), revision=1, content_hash=digest, slots=content["slots"], coverage=content["coverage"], last_attempt_at=now, next_poll_at=now+provider.min_poll_seconds*1000); db.add(snapshot)
    else:
        if changed: snapshot.revision += 1; snapshot.content_hash=digest; snapshot.slots=content["slots"]; snapshot.coverage=content["coverage"]
        snapshot.last_attempt_at=now; snapshot.next_poll_at=now+provider.min_poll_seconds*1000
    snapshot.last_success_at=int(body.fetched_at.timestamp()*1000); snapshot.last_error_code=None; snapshot.reported_stale_at=None
    if changed: emit(db, "venue.changed", actor=user, payload={"venue_id": venue_id, "local_date": body.local_date.isoformat(), "revision": snapshot.revision})
    db.commit(); return {"venue_id": venue_id, "local_date": body.local_date.isoformat(), "revision": snapshot.revision, "changed": changed}


def validate_query_day(venue: Venue, day: date):
    today = datetime.now(ZoneInfo(venue.timezone)).date()
    if not today <= day <= date.fromordinal(today.toordinal() + 31):
        raise HTTPException(422, detail={"code": "DATE_OUT_OF_RANGE", "message": "只能查询今天起 31 天内的场地。"})


def snapshot_response(venue, provider, snapshot, day):
    fresh_until = (snapshot.last_success_at or 0) + provider.fresh_for_seconds * 1000
    fresh = bool(provider.enabled and venue.enabled and snapshot.last_success_at
                 and not login.paused(provider) and not snapshot.last_error_code and snapshot.coverage.get("complete")
                 and now_ms() <= fresh_until)
    return {"venue_id": venue.id, "local_date": day.isoformat(), "slots": snapshot.slots,
            "coverage": snapshot.coverage, "revision": snapshot.revision,
            "last_success_at": from_ms(snapshot.last_success_at),
            "fresh_until": from_ms(fresh_until) if snapshot.last_success_at else None,
            "fresh": fresh, "last_error_code": snapshot.last_error_code,
            "next_poll_at": from_ms(snapshot.next_poll_at),
            "available_count": sum(s["status"] == "available" for s in snapshot.slots) if fresh else 0}


@router.get("/venues/{venue_id}/slots")
async def slots(venue_id: str, date: date, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    venue = db.get(Venue, venue_id)
    if not venue or not venue.enabled:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "场馆不存在。"})
    validate_query_day(venue, date)
    provider = db.get(ProviderConfig, venue.provider_id)
    snapshot = get_snapshot(db, venue_id, date)
    if provider.enabled and provider.adapter_key != "manual" and (
            not snapshot or not snapshot.last_success_at or snapshot.last_error_code
            or snapshot.last_success_at + provider.fresh_for_seconds * 1000 < now_ms()):
        snapshot = await refresh_day(db, venue, provider, date)
    if not snapshot:
        raise HTTPException(503, detail={"code": "SOURCE_PENDING", "message": "暂无数据或来源正在冷却，请稍后查询。"})
    return snapshot_response(venue, provider, snapshot, date)


@router.post("/venues/{venue_id}/refresh", status_code=202)
async def refresh(venue_id: str, date: date, request: Request, activity_id: str | None = None,
                  db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_csrf(request)
    venue = db.get(Venue, venue_id)
    if not venue or not venue.enabled:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "场馆不存在。"})
    if activity_id:
        activity = db.get(Activity, activity_id)
        require_member(db, activity, user)
        if venue_id not in activity.venue_preferences:
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "场馆不属于这场活动。"})
    validate_query_day(venue, date)
    provider = db.get(ProviderConfig, venue.provider_id)
    snapshot = await refresh_day(db, venue, provider, date)
    return {"refresh_key": f"{venue_id}:{date.isoformat()}", "shared": True,
            "snapshot": snapshot_response(venue, provider, snapshot, date) if snapshot else None}


def compute_candidates(db: Session, activity: Activity, limit: int = 20, duration_minutes: int | None = None):
    ps = db.scalars(select(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active").order_by(Participant.join_order)).all(); people=[]
    for p in ps:
        rows=db.scalars(select(AvailabilityRule).where(AvailabilityRule.user_id==p.user_id, (AvailabilityRule.activity_id.is_(None)) | (AvailabilityRule.activity_id==activity.id))).all()
        rules=[Rule(r.source,r.state,r.kind,r.edit_seq,datetime.fromtimestamp(r.start_at/1000,timezone.utc) if r.start_at else None,datetime.fromtimestamp(r.end_at/1000,timezone.utc) if r.end_at else None,r.recurrence,r.id) for r in rows]
        people.append({"id":p.id,"required":p.required,"state_for":lambda start,end,rules=rules: summarize_window(resolve_availability(rules,Interval(start,end),activity.timezone),Interval(start,end))})
    days=[]; diagnostics=[]
    if not activity.venue_preferences:
        diagnostics.append({"code":"NO_VENUE","message":"尚未选择活动场馆，请主持人先选择场馆。"})
    today=datetime.now(ZoneInfo(activity.timezone)).date()
    for venue_id in activity.venue_preferences:
        venue=db.get(Venue,venue_id)
        provider=db.get(ProviderConfig,venue.provider_id) if venue else None
        if not venue or not venue.enabled or not provider or not provider.enabled:
            diagnostics.append({"code":"VENUE_DISABLED","message":"所选场馆已停用，请重新选择。"});continue
        snapshots={x.local_date:x for x in db.scalars(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue_id,VenueSnapshot.local_date>=activity.date_from,VenueSnapshot.local_date<=activity.date_to))}
        current=max(date.fromisoformat(activity.date_from),today)
        while current<=date.fromisoformat(activity.date_to):
            key=current.isoformat();snapshot=snapshots.get(key)
            fresh_until=(snapshot.last_success_at or 0)+provider.fresh_for_seconds*1000 if snapshot else 0
            fresh=bool(snapshot and snapshot.last_success_at and not login.paused(provider) and not snapshot.last_error_code and snapshot.coverage.get("complete") and now_ms()<=fresh_until)
            if not fresh:
                code="AUTH_REQUIRED" if login.paused(provider) else "SOURCE_ERROR" if snapshot and snapshot.last_error_code else "STALE_DATA" if snapshot and snapshot.last_success_at else "NO_DATA"
                message={"AUTH_REQUIRED":"场馆登录失效，等待管理员更新。","SOURCE_ERROR":"场馆查询失败，请查看可用场地页面。","STALE_DATA":"场地余量已过期，需刷新。","NO_DATA":"尚未取得场地余量。"}[code]
                diagnostics.append({"code":code,"venue_id":venue_id,"local_date":key,"message":f"{venue.name} {key}：{message}"})
            days.append({"venue_id":venue.id,"venue_name":venue.name,"local_date":key,
                "slots":snapshot.slots if snapshot else [],"coverage":snapshot.coverage if snapshot else {"identity_mode":"court"},
                "last_success_at":from_ms(snapshot.last_success_at) if snapshot else None,
                "fresh_until":from_ms(fresh_until) if fresh_until else None,"fresh":fresh})
            current=date.fromordinal(current.toordinal()+1)
    result=generate_candidates({"version":activity.version,"duration_minutes":duration_minutes or activity.duration_minutes,
        "min_players":activity.min_players,"max_players":activity.max_players,"court_count":activity.court_count,
        "venue_preferences":activity.venue_preferences,"daily_windows":activity.daily_windows,"timezone":activity.timezone},
        people,days,datetime.now(timezone.utc))
    counts=Counter(x["classification"] for x in result["other_windows"])
    messages={"insufficient_players":"这些时段人数不足，或核心成员没有全程标为空闲。", "too_many_required":"核心成员数量超过活动人数上限。", "people_only":"这些时段人员有空，但缺少足够连续球场或有效余量。", "needs_court_check":"这些时段需要核实具体球场。"}
    diagnostics.extend({"code":key.upper(),"count":count,"message":messages[key]} for key,count in counts.items())
    result.update(activity_version=activity.version,generated_at=datetime.now(timezone.utc).isoformat(),diagnostics=diagnostics)
    result["candidates"]=result["candidates"][:limit]
    result["other_windows"]=result["other_windows"][:50]
    return result


@router.get("/activities/{activity_id}/candidates")
async def candidates(activity_id: str, request: Request, limit: int = 20, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    return compute_candidates(db, activity, limit)


@router.get("/activities/{activity_id}/candidates/preview")
async def preview_candidates(activity_id: str, request: Request,
        duration_minutes: int = Query(ge=30, le=360, multiple_of=15), db: Session = Depends(get_db)):
    user = require_user(request, db)
    activity = db.get(Activity, activity_id)
    require_member(db, activity, user)
    if activity.status != "collecting":
        raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "请先回到收集时间阶段，再预览活动调整。"})
    return {**compute_candidates(db, activity, duration_minutes=duration_minutes), "preview": True,
        "original_duration_minutes": activity.duration_minutes, "duration_minutes": duration_minutes}


def login_provider(provider_id, db):
    provider = db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "场馆来源不存在。"})
    return provider


@router.get("/settings/providers/{provider_id}/login")
async def login_status(provider_id: str, request: Request, db: Session = Depends(get_db)):
    admin(request, db, False)
    return login.status(login_provider(provider_id, db))


@router.post("/settings/providers/{provider_id}/login")
async def start_login(provider_id: str, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    provider = login_provider(provider_id, db)
    extension = extension_for(provider.adapter_key)
    if not extension or not hasattr(extension, "start_login"):
        raise HTTPException(422, detail={"code": "UNSUPPORTED", "message": "该来源不支持本机登录更新。"})
    try:
        extension.start_login()
    except RuntimeError:
        raise HTTPException(503, detail={"code": "LOCAL_TERMINAL_UNAVAILABLE", "message": "无法打开服务器本机终端，请在服务器桌面操作。"}) from None
    return login.status(provider)


@router.delete("/settings/providers/{provider_id}/login")
async def cancel_login(provider_id: str, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    provider = login_provider(provider_id, db)
    extension = extension_for(provider.adapter_key)
    if extension and hasattr(extension, "cancel_login"):
        extension.cancel_login()
    return login.status(provider)


@router.post("/activities/{activity_id}/candidates/refresh")
async def refresh_candidates(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_user(request,db);require_csrf(request)
    activity=db.get(Activity,activity_id);require_member(db,activity,user)
    deadline=monotonic_time.monotonic()+20
    for vid in activity.venue_preferences:
        venue=db.get(Venue,vid)
        if not venue or not venue.enabled:continue
        provider=db.get(ProviderConfig,venue.provider_id)
        if not provider or not provider.enabled or provider.adapter_key=="manual" or login.blocked(provider):continue
        current=max(date.fromisoformat(activity.date_from),datetime.now(ZoneInfo(activity.timezone)).date())
        while current<=date.fromisoformat(activity.date_to) and monotonic_time.monotonic()<deadline:
            snapshot=get_snapshot(db,vid,current)
            if not snapshot or snapshot.next_poll_at<=now_ms():
                await refresh_day(db,venue,provider,current)
                # Respect the same source spacing as the background worker.
                if provider.min_request_interval_seconds<=3:
                    await asyncio.sleep(provider.min_request_interval_seconds)
            current=date.fromordinal(current.toordinal()+1)
    return compute_candidates(db,activity)
