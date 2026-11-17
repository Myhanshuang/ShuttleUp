from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..common import from_ms
from ..models import Activity, ActivityPlan, Event, Participant, User, Venue
from .attention import attention

STATUS_LABELS = {"collecting": "收集时间", "booking": "待订场", "confirmed": "已确定", "finished": "待结算", "cancelled": "已取消"}


def participant_for(db: Session, activity_id: str, user_id: str, include_inactive: bool = False) -> Participant | None:
    conditions = [Participant.activity_id == activity_id, Participant.user_id == user_id]
    if not include_inactive:
        conditions.append(Participant.membership == "active")
    return db.scalar(select(Participant).where(*conditions))


def require_member(db: Session, activity: Activity | None, user: User) -> Participant:
    if not activity:
        from fastapi import HTTPException
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "活动不存在。"})
    participant = participant_for(db, activity.id, user.id)
    if not participant:
        from fastapi import HTTPException
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "你不是这场活动的成员。"})
    return participant


def require_host(activity: Activity, user: User) -> None:
    if activity.host_user_id != user.id:
        from fastapi import HTTPException
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "只有主持人可以执行此操作。"})


def activity_dto(db: Session, activity: Activity, viewer: User) -> dict:
    participant = participant_for(db, activity.id, viewer.id, include_inactive=True)
    count = db.scalar(select(func.count()).select_from(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active")) or 0
    current_plan=db.get(ActivityPlan,activity.current_plan_id) if activity.current_plan_id else None
    return {
        "id": activity.id, "short_code": activity.short_code, "title": activity.title,
        "host_user_id": activity.host_user_id, "is_host": activity.host_user_id == viewer.id,
        "status": activity.status, "status_label": STATUS_LABELS[activity.status], "timezone": activity.timezone,
        "date_from": activity.date_from, "date_to": activity.date_to, "daily_windows": activity.daily_windows,
        "duration_minutes": activity.duration_minutes, "min_players": activity.min_players,
        "max_players": activity.max_players, "court_count": activity.court_count,
        "venue_preferences": activity.venue_preferences, "decision_deadline": from_ms(activity.decision_deadline),
        "venue_summary": [{"id": v.id, "name": v.name} for v in db.scalars(select(Venue).where(Venue.id.in_(activity.venue_preferences)))],
        "billing_status": activity.billing_status, "bill_generation": activity.bill_generation,
        "current_plan_id": activity.current_plan_id,
        "current_plan": {"id":current_plan.id,"plan_no":current_plan.plan_no,"starts_at":from_ms(current_plan.starts_at),"ends_at":from_ms(current_plan.ends_at),"venue_id":current_plan.venue_id,"court_ids":current_plan.court_ids,"roster_participant_ids":current_plan.roster_participant_ids,"snapshot":current_plan.snapshot} if current_plan else None,
        "next_action": attention(db, activity, viewer, participant, current_plan),
        "archived_at": from_ms(activity.archived_at), "cancel_reason": activity.cancel_reason,
        "participant_count": count, "my_participant_id": participant.id if participant else None,
        "my_membership": participant.membership if participant else None, "version": activity.version,
    }


def emit(db: Session, event_type: str, *, activity: Activity | None = None, actor: User | None = None, owner_user_id: str | None = None, payload: dict | None = None):
    db.add(Event(type=event_type, activity_id=activity.id if activity else None, actor_user_id=actor.id if actor else None, owner_user_id=owner_user_id, resource_version=activity.version if activity else 1, payload=payload or {}))
