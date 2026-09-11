import asyncio
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
import httpx

from ..activities.service import emit
from ..auth.service import require_csrf, require_user
from ..config import get_settings
from ..db import get_db
from ..models import AvailabilityRule, ScheduleImport
from .routes import RuleCreate
from .wakeup import WakeUpImporter, expand_occurrences

router = APIRouter(tags=["schedule-imports"])
PREVIEWS: dict[tuple[str, str], tuple[float, object, list[dict]]] = {}


class PreviewRequest(BaseModel):
    share_text: str = Field(min_length=1, max_length=4000)
    fixture_payload: str | None = None


class ConfirmRequest(BaseModel):
    preview_id: str
    label: str = Field(min_length=1, max_length=80)
    baseline_rules: list[RuleCreate] = Field(default_factory=list, max_length=20)
    expected_revision: int


@router.post("/me/imports/wakeup/preview")
async def preview(body: PreviewRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); importer = WakeUpImporter(get_settings().wakeup_share_endpoint)
    try:
        if body.fixture_payload and get_settings().demo_mode: payload = body.fixture_payload.encode()
        else: payload = await importer.fetch(body.share_text)
        schedule = importer.normalize(payload); occurrences = expand_occurrences(schedule)
    except RuntimeError:
        raise HTTPException(503, detail={"code": "WAKEUP_NOT_CONFIGURED", "message": "WakeUp 真实导入端点尚未配置。"})
    except (ValueError, httpx.HTTPError) as error:
        raise HTTPException(502, detail={"code": "WAKEUP_IMPORT_FAILED", "message": str(error)})
    preview_id = str(uuid.uuid4()); PREVIEWS[(user.id, preview_id)] = (time.monotonic()+600, schedule, occurrences)
    return {"preview_id": preview_id, "term": {"start": schedule.term_start_monday.isoformat(), "end": schedule.term_end_date.isoformat(), "timezone": schedule.timezone}, "periods": schedule.periods, "busy_occurrences": occurrences, "summary": {"course_count": len(schedule.lessons), "occurrence_count": len(occurrences)}}


@router.post("/me/imports/wakeup/confirm")
async def confirm(body: ConfirmRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); entry = PREVIEWS.pop((user.id, body.preview_id), None)
    if not entry or entry[0] < time.monotonic(): raise HTTPException(410, detail={"code": "PREVIEW_EXPIRED", "message": "预览已过期，请重新导入。"})
    if user.availability_revision != body.expected_revision: raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "时间表刚刚有更新。", "current_version": user.availability_revision})
    _, schedule, occurrences = entry
    old = db.scalar(select(ScheduleImport).where(ScheduleImport.user_id == user.id, ScheduleImport.provider_key == "wakeup", ScheduleImport.label == body.label))
    if old:
        db.execute(delete(AvailabilityRule).where(AvailabilityRule.import_id == old.id)); db.delete(old); db.flush()
    imported = ScheduleImport(user_id=user.id, provider_key="wakeup", label=body.label, term_start_date=schedule.term_start_monday.isoformat(), term_end_date=schedule.term_end_date.isoformat(), timezone=schedule.timezone, payload_hash=schedule.payload_hash, occurrence_count=len(occurrences))
    db.add(imported); db.flush(); user.availability_revision += 1
    for occurrence in occurrences:
        db.add(AvailabilityRule(user_id=user.id, import_id=imported.id, source="course", state="busy", kind="once", start_at=int(datetime.fromisoformat(occurrence["starts_at"]).timestamp()*1000), end_at=int(datetime.fromisoformat(occurrence["ends_at"]).timestamp()*1000), edit_seq=user.availability_revision))
    for rule in body.baseline_rules:
        if rule.source != "baseline": raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "确认导入时只接受基础可约时间。"})
        db.add(AvailabilityRule(user_id=user.id, source="baseline", state=rule.state, kind=rule.kind, start_at=int(rule.start_at.timestamp()*1000) if rule.start_at else None, end_at=int(rule.end_at.timestamp()*1000) if rule.end_at else None, recurrence=rule.recurrence, edit_seq=user.availability_revision))
    emit(db, "availability.changed", actor=user, owner_user_id=user.id, payload={"revision": user.availability_revision}); db.commit()
    return {"id": imported.id, "label": imported.label, "occurrence_count": imported.occurrence_count, "revision": user.availability_revision}


@router.get("/me/imports")
async def imports(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); items = db.scalars(select(ScheduleImport).where(ScheduleImport.user_id == user.id)).all()
    return {"items": [{"id": i.id, "provider_key": i.provider_key, "label": i.label, "term_start_date": i.term_start_date, "term_end_date": i.term_end_date, "occurrence_count": i.occurrence_count} for i in items], "next_cursor": None}


@router.delete("/me/imports/{import_id}",status_code=204)
async def delete_import(import_id: str,expected_revision: int,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request);item=db.get(ScheduleImport,import_id)
    if not item or item.user_id!=user.id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"导入记录不存在。"})
    if user.availability_revision!=expected_revision: raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"时间表刚刚有更新。","current_version":user.availability_revision})
    db.execute(delete(AvailabilityRule).where(AvailabilityRule.import_id==item.id));db.delete(item);user.availability_revision+=1;emit(db,"availability.changed",actor=user,owner_user_id=user.id,payload={"revision":user.availability_revision});db.commit()
