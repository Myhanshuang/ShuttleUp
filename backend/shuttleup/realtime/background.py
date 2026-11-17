import asyncio
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Activity, BotActivityLink, BotContext, Event, Notification, ProviderConfig, Venue, VenueSnapshot, now_ms
from ..venues.service import refresh_day
from ..venues.providers import supported_provider
from ..venues.login import blocked

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
                if not provider or not provider.enabled or provider.adapter_key == "manual" or not supported_provider(provider.adapter_key): continue
                if blocked(provider): continue
                current=max(date.fromisoformat(activity.date_from), datetime.now(timezone.utc).astimezone(ZoneInfo(venue.timezone)).date()); final=min(date.fromisoformat(activity.date_to),date.fromordinal(current.toordinal()+31))
                while current<=final:
                    snapshot=db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id==venue.id,VenueSnapshot.local_date==current.isoformat()))
                    if not snapshot or snapshot.next_poll_at<=now: result.append((provider.id,venue.id,current.isoformat()))
                    current=date.fromordinal(current.toordinal()+1)
    return result[:1]


async def fetch_due(provider_id: str, venue_id: str, local_date: str):
    with SessionLocal() as db:
        config = db.get(ProviderConfig, provider_id)
        venue = db.get(Venue, venue_id)
        if config and venue:
            await refresh_day(db, venue, config, date.fromisoformat(local_date))


async def venue_worker(stop: asyncio.Event):
    while not stop.is_set():
        queries=await asyncio.to_thread(due_queries)
        for query in queries: await fetch_due(*query)
        try: await asyncio.wait_for(stop.wait(),2)
        except asyncio.TimeoutError: pass

