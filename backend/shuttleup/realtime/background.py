import asyncio
import hashlib
import json
import os
from datetime import date, datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Activity, BotActivityLink, BotContext, Event, Notification, ProviderConfig, Venue, VenueSnapshot, now_ms
from ..venues.providers import StandardJsonProvider

NOTIFY_TYPES={"activity.created","activity.cancelled","activity.finished","plan.selected","booking.confirmed","bill.published","bill.settled","payment.confirmed"}


def process_events_once():
    with SessionLocal.begin() as db:
        events=db.scalars(select(Event).where(Event.processed_at.is_(None)).order_by(Event.seq).limit(100)).all()
        for event in events:
            if event.activity_id and event.type in NOTIFY_TYPES:
                activity=db.get(Activity,event.activity_id); links=db.scalars(select(BotActivityLink).where(BotActivityLink.activity_id==event.activity_id,BotActivityLink.notifications_enabled.is_(True))).all()
                text={"activity.created":f"新活动：{activity.title}（{activity.short_code}）。","activity.cancelled":f"{activity.title} 已取消。","activity.finished":f"{activity.title} 已结束，等待核对到场和结算。","plan.selected":f"{activity.title} 已选择方案，等待订场。","booking.confirmed":f"{activity.title} 的场地已订好。","bill.published":f"{activity.title} 的账单已发布，请查看个人应收应付。","bill.settled":f"{activity.title} 已全部结清。","payment.confirmed":f"{activity.title} 有一笔收款已确认。"}[event.type]
                for link in links:
                    db.add(Notification(event_seq=event.seq,dedupe_key=f"event:{event.event_id}:context:{link.context_id}",target_type="bot_context",target_context_id=link.context_id,payload={"event_type":event.type,"text":text,"links":[{"label":"查看活动","path":f"/a/{activity.id}"}]}))
            event.processed_at=now_ms()


async def event_worker(stop: asyncio.Event):
    while not stop.is_set():
        await asyncio.to_thread(process_events_once)
        try: await asyncio.wait_for(stop.wait(),1)
        except asyncio.TimeoutError: pass


def due_queries():
    now=now_ms(); result=[]
    with SessionLocal() as db:
        active=db.scalars(select(Activity).where(Activity.status.in_(["collecting","booking"]))).all()
        for activity in active:
            for venue_id in activity.venue_preferences:
                venue=db.get(Venue,venue_id)
                if not venue or not venue.enabled: continue
                provider=db.get(ProviderConfig,venue.provider_id)
                if not provider or not provider.enabled or provider.adapter_key!="standard_json": continue
                current=date.fromisoformat(activity.date_from); final=date.fromisoformat(activity.date_to)
                while current<=final:
                    snapshot=db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue.id,VenueSnapshot.local_date==current.isoformat()))
                    if not snapshot or snapshot.next_poll_at<=now: result.append((provider.id,venue.id,current.isoformat()))
                    current=date.fromordinal(current.toordinal()+1)
    return result[:1]


async def fetch_due(provider_id: str,venue_id: str,local_date: str):
    with SessionLocal() as db:
        config=db.get(ProviderConfig,provider_id); venue=db.get(Venue,venue_id); settings=dict(config.config); credential=os.getenv(config.credential_env) if config.credential_env else None
        headers={"Authorization":f"Bearer {credential}"} if credential else {}
        provider=StandardJsonProvider(settings["endpoint"],settings["allowed_host"],headers); external=venue.external_venue_id; fresh=config.fresh_for_seconds; poll=config.min_poll_seconds
    try: result=await provider.fetch_day(external,date.fromisoformat(local_date)); error=None
    except Exception as exc: result=None; error=type(exc).__name__
    with SessionLocal.begin() as db:
        snapshot=db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue_id,VenueSnapshot.local_date==local_date)); now=now_ms()
        if error:
            if snapshot: snapshot.last_attempt_at=now; snapshot.last_error_code=error; snapshot.next_poll_at=now+poll*1000
            return
        content={"coverage":result.coverage.model_dump(mode="json"),"slots":[s.model_dump(mode="json") for s in result.slots]}; digest=hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest(); changed=not snapshot or snapshot.content_hash!=digest
        if not snapshot: snapshot=VenueSnapshot(venue_id=venue_id,local_date=local_date,revision=1,content_hash=digest,slots=content["slots"],coverage=content["coverage"],last_attempt_at=now,next_poll_at=now+poll*1000); db.add(snapshot)
        else:
            if changed: snapshot.revision+=1;snapshot.content_hash=digest;snapshot.slots=content["slots"];snapshot.coverage=content["coverage"]
            snapshot.last_attempt_at=now;snapshot.next_poll_at=now+poll*1000
        snapshot.last_success_at=int(result.fetched_at.timestamp()*1000);snapshot.last_error_code=None;snapshot.reported_stale_at=None
        if changed: db.add(Event(type="venue.changed",activity_id=None,resource_version=snapshot.revision,payload={"venue_id":venue_id,"local_date":local_date,"revision":snapshot.revision}))


async def venue_worker(stop: asyncio.Event):
    while not stop.is_set():
        queries=await asyncio.to_thread(due_queries)
        for query in queries: await fetch_due(*query)
        try: await asyncio.wait_for(stop.wait(),2)
        except asyncio.TimeoutError: pass

