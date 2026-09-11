import hashlib
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..activities.service import emit, require_member
from ..auth.service import require_csrf, require_user
from ..common import from_ms
from ..db import get_db
from ..models import Activity, AvailabilityRule, Participant, ProviderConfig, User, Venue, VenueSnapshot, now_ms
from ..availability.engine import Interval, Rule, resolve_availability, summarize_window
from .candidates import generate_candidates
from .providers import VenueDayResult

router = APIRouter(tags=["venues"])


class ProviderCreate(BaseModel):
    key: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_-]+$")
    adapter_key: str = Field(pattern="^(manual|standard_json|site_adapter)$")
    label: str = Field(min_length=1, max_length=80)
    config: dict = Field(default_factory=dict)
    credential_env: str | None = Field(default=None, pattern=r"^VENUE_[A-Z0-9_]+$")
    min_poll_seconds: int = Field(default=30, ge=10)
    min_request_interval_seconds: int = Field(default=2, ge=1)
    fresh_for_seconds: int = Field(default=90, ge=10)


class VenueCreate(BaseModel):
    provider_id: str
    external_venue_id: str
    name: str
    address: str = ""
    timezone: str = "Asia/Shanghai"
    booking_url: str = ""
    hourly_rate_cents: int | None = Field(default=None, ge=0)


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
    admin(request, db); model = ProviderConfig(**body.model_dump()); db.add(model); db.commit(); return {"id": model.id, **body.model_dump()}


@router.get("/settings/providers")
async def list_providers(request: Request,db: Session=Depends(get_db)):
    admin(request,db,False);items=db.scalars(select(ProviderConfig).order_by(ProviderConfig.label)).all();return {"items":[{"id":p.id,"key":p.key,"adapter_key":p.adapter_key,"label":p.label,"min_poll_seconds":p.min_poll_seconds,"min_request_interval_seconds":p.min_request_interval_seconds,"fresh_for_seconds":p.fresh_for_seconds,"enabled":p.enabled,"credential_env":p.credential_env,"config":p.config,"version":p.version} for p in items],"next_cursor":None}


@router.post("/settings/venues", status_code=201)
async def create_venue(body: VenueCreate, request: Request, db: Session = Depends(get_db)):
    admin(request, db)
    if not db.get(ProviderConfig, body.provider_id): raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "场馆来源不存在。"})
    model = Venue(**body.model_dump()); db.add(model); db.commit(); return {"id": model.id, **body.model_dump()}


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


@router.get("/venues/{venue_id}/slots")
async def slots(venue_id: str, date: date, request: Request, db: Session = Depends(get_db)):
    require_user(request, db); venue = db.get(Venue, venue_id); snapshot = db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id == venue_id, VenueSnapshot.local_date == date.isoformat()))
    if not venue or not snapshot: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "暂无该日场地数据。"})
    provider = db.get(ProviderConfig, venue.provider_id); fresh_until = (snapshot.last_success_at or 0) + provider.fresh_for_seconds*1000
    return {"venue_id": venue_id, "local_date": date.isoformat(), "slots": snapshot.slots, "coverage": snapshot.coverage, "revision": snapshot.revision, "last_success_at": from_ms(snapshot.last_success_at), "fresh_until": from_ms(fresh_until), "fresh": now_ms() <= fresh_until, "last_error_code": snapshot.last_error_code}


@router.post("/venues/{venue_id}/refresh",status_code=202)
async def refresh(venue_id: str,date: date,activity_id: str,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);activity=db.get(Activity,activity_id);require_member(db,activity,user);venue=db.get(Venue,venue_id)
    if not venue or venue_id not in activity.venue_preferences: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"场馆不属于这场活动。"})
    snapshot=db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue_id,VenueSnapshot.local_date==date.isoformat()))
    if snapshot:snapshot.next_poll_at=0;db.commit()
    return {"refresh_key":f"{venue_id}:{date.isoformat()}","shared":True}


def compute_candidates(db: Session, activity: Activity, limit: int = 20):
    ps = db.scalars(select(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active").order_by(Participant.join_order)).all(); people=[]
    for p in ps:
        rows=db.scalars(select(AvailabilityRule).where(AvailabilityRule.user_id==p.user_id, (AvailabilityRule.activity_id.is_(None)) | (AvailabilityRule.activity_id==activity.id))).all()
        rules=[Rule(r.source,r.state,r.kind,r.edit_seq,datetime.fromtimestamp(r.start_at/1000,timezone.utc) if r.start_at else None,datetime.fromtimestamp(r.end_at/1000,timezone.utc) if r.end_at else None,r.recurrence,r.id) for r in rows]
        people.append({"id":p.id,"required":p.required,"state_for":lambda start,end,rules=rules: summarize_window(resolve_availability(rules,Interval(start,end),activity.timezone),Interval(start,end))})
    days=[]
    for venue_id in activity.venue_preferences:
        venue=db.get(Venue,venue_id)
        if not venue: continue
        provider=db.get(ProviderConfig,venue.provider_id)
        for snapshot in db.scalars(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue_id,VenueSnapshot.local_date>=activity.date_from,VenueSnapshot.local_date<=activity.date_to)).all():
            fresh_until=(snapshot.last_success_at or 0)+provider.fresh_for_seconds*1000
            days.append({"venue_id":venue.id,"venue_name":venue.name,"slots":snapshot.slots,"coverage":snapshot.coverage,"last_success_at":from_ms(snapshot.last_success_at),"fresh_until":from_ms(fresh_until),"fresh":now_ms()<=fresh_until})
    result=generate_candidates({"version":activity.version,"duration_minutes":activity.duration_minutes,"min_players":activity.min_players,"max_players":activity.max_players,"court_count":activity.court_count,"venue_preferences":activity.venue_preferences},people,days,datetime.now(timezone.utc)); result["activity_version"]=activity.version; result["generated_at"]=datetime.now(timezone.utc).isoformat(); result["candidates"]=result["candidates"][:limit]; return result


@router.get("/activities/{activity_id}/candidates")
async def candidates(activity_id: str, request: Request, limit: int = 20, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    return compute_candidates(db, activity, limit)
