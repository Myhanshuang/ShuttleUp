from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth.service import require_csrf, require_user
from ..common import from_ms, to_ms
from ..db import get_db
from ..models import Activity, AvailabilityRule, Participant
from ..activities.service import emit, require_member
from .engine import Interval, Rule, resolve_availability, summarize_window

router = APIRouter(tags=["availability"])


class RuleCreate(BaseModel):
    state: str = Field(pattern="^(free|busy|unknown)$")
    source: str = Field(pattern="^(baseline|weekly|one_off|activity)$")
    kind: str = Field(pattern="^(once|weekly)$")
    start_at: datetime | None = None
    end_at: datetime | None = None
    recurrence: dict | None = None
    activity_id: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "once" and (not self.start_at or not self.end_at or self.end_at <= self.start_at): raise ValueError("一次性规则需要有效时间段")
        if self.kind == "weekly" and not self.recurrence: raise ValueError("周期规则需要 recurrence")
        if self.source == "activity" and not self.activity_id: raise ValueError("活动规则需要 activity_id")
        if self.source != "activity" and self.activity_id: raise ValueError("只有活动规则可以指定 activity_id")
        return self


class RulesCreate(BaseModel):
    rules: list[RuleCreate] = Field(min_length=1, max_length=100)
    expected_revision: int


def to_rule(model: AvailabilityRule) -> Rule:
    return Rule(model.source, model.state, model.kind, model.edit_seq,
        datetime.fromtimestamp(model.start_at / 1000, timezone.utc) if model.start_at else None,
        datetime.fromtimestamp(model.end_at / 1000, timezone.utc) if model.end_at else None,
        model.recurrence, model.id)


@router.get("/me/availability")
async def get_availability(request: Request, from_: datetime | None = None, to: datetime | None = None, activity_id: str | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db)
    query = select(AvailabilityRule).where(AvailabilityRule.user_id == user.id).where((AvailabilityRule.activity_id.is_(None)) | (AvailabilityRule.activity_id == activity_id))
    rules = db.scalars(query.order_by(AvailabilityRule.edit_seq)).all()
    response = {"revision": user.availability_revision, "rules": [{"id": r.id, "state": r.state, "source": r.source, "kind": r.kind, "start_at": from_ms(r.start_at), "end_at": from_ms(r.end_at), "recurrence": r.recurrence, "activity_id": r.activity_id} for r in rules]}
    if from_ and to:
        segments = resolve_availability([to_rule(r) for r in rules], Interval(from_, to), user.timezone)
        response["resolved"] = [{"start": s.span.start.isoformat(), "end": s.span.end.isoformat(), "state": s.state, "source": s.source} for s in segments]
    return response


@router.post("/me/availability/rules", status_code=201)
async def create_rules(body: RulesCreate, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request)
    if user.availability_revision != body.expected_revision:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "时间表刚刚有更新。", "current_version": user.availability_revision})
    user.availability_revision += 1
    created = []
    for rule in body.rules:
        model = AvailabilityRule(user_id=user.id, activity_id=rule.activity_id, source=rule.source, state=rule.state, kind=rule.kind,
            start_at=to_ms(rule.start_at), end_at=to_ms(rule.end_at), recurrence=rule.recurrence, edit_seq=user.availability_revision)
        db.add(model); created.append(model)
    emit(db, "availability.changed", actor=user, owner_user_id=user.id, payload={"revision": user.availability_revision, "activity_ids": sorted({r.activity_id for r in body.rules if r.activity_id})})
    db.commit()
    return {"revision": user.availability_revision, "rules": [{"id": r.id, "state": r.state, "source": r.source} for r in created]}


@router.delete("/me/availability/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, expected_revision: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); rule = db.get(AvailabilityRule, rule_id)
    if not rule or rule.user_id != user.id: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "时间规则不存在。"})
    if rule.source == "course": raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "课程规则请通过重新导入或删除课表处理。"})
    if user.availability_revision != expected_revision: raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "时间表刚刚有更新。", "current_version": user.availability_revision})
    db.delete(rule); user.availability_revision += 1; emit(db, "availability.changed", actor=user, owner_user_id=user.id, payload={"revision": user.availability_revision}); db.commit()


@router.get("/activities/{activity_id}/availability")
async def shared_availability(activity_id: str,request: Request,from_: datetime=Query(alias="from"),to: datetime=Query(),db: Session=Depends(get_db)):
    user=require_user(request,db);activity=db.get(Activity,activity_id);require_member(db,activity,user)
    if to<=from_ or (to-from_).days>14: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"查询时间范围无效或超过 14 天。"})
    participants=db.scalars(select(Participant).where(Participant.activity_id==activity_id,Participant.membership=="active").order_by(Participant.join_order)).all();resolved_by={}
    for p in participants:
        rows=db.scalars(select(AvailabilityRule).where(AvailabilityRule.user_id==p.user_id,(AvailabilityRule.activity_id.is_(None))|(AvailabilityRule.activity_id==activity_id))).all();resolved=resolve_availability([to_rule(r) for r in rows],Interval(from_,to),activity.timezone);resolved_by[p.id]=resolved
    boundaries=sorted({from_,to,*[s.span.start for segments in resolved_by.values() for s in segments],*[s.span.end for segments in resolved_by.values() for s in segments]});segments=[]
    for start,end in zip(boundaries,boundaries[1:]):
        states={p.id:summarize_window(resolved_by[p.id],Interval(start,end)) for p in participants};segments.append({"starts_at":start.isoformat(),"ends_at":end.isoformat(),"free_count":sum(v=="free" for v in states.values()),"busy_count":sum(v=="busy" for v in states.values()),"unknown_count":sum(v=="unknown" for v in states.values()),"states":[{"participant_id":pid,"state":state} for pid,state in states.items()]})
    return {"activity_id":activity_id,"from":from_.isoformat(),"to":to.isoformat(),"participants":[{"id":p.id,"display_name":p.display_name,"required":p.required} for p in participants],"segments":segments}
