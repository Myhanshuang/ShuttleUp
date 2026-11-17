"""Shared refresh, throttling and snapshot storage for API and background jobs."""
import asyncio
import hashlib
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Event, ProviderConfig, Venue, VenueSnapshot, now_ms
from .providers import build_provider
from .providers import VenueSourceError
from .login import AUTH_ERRORS, blocked, paused, pause, verified, credential_revision

# The deployment uses one application worker. Database attempt times also retain
# cooldowns across restarts; these locks coalesce concurrent requests in-process.
_locks: dict[str, asyncio.Lock] = {}


def get_snapshot(db, venue_id, day):
    return db.scalar(select(VenueSnapshot).where(VenueSnapshot.venue_id == venue_id,
                                                VenueSnapshot.local_date == day.isoformat()))


async def refresh_day(db: Session, venue: Venue, provider: ProviderConfig, day: date):
    async with _locks.setdefault(provider.id, asyncio.Lock()):
        db.expire_all()
        snapshot = get_snapshot(db, venue.id, day)
        now = now_ms()
        auth = provider.config.get('_login_state', {})
        if blocked(provider):
            if snapshot is None:
                start = datetime.combine(day, time(), ZoneInfo(venue.timezone))
                snapshot = VenueSnapshot(venue_id=venue.id, local_date=day.isoformat(), revision=0,
                    content_hash='', slots=[], coverage={'complete': False, 'identity_mode': 'court'},
                    last_attempt_at=now, next_poll_at=now)
                db.add(snapshot)
            snapshot.last_error_code = auth.get('error', 'AUTH_REQUIRED')
            db.commit()
            return snapshot
        replacing_credential = paused(provider)
        if snapshot and snapshot.next_poll_at > now and not replacing_credential:
            return snapshot
        if not venue.enabled or not provider.enabled or provider.adapter_key == 'manual':
            return snapshot
        last_attempt = db.scalar(select(func.max(VenueSnapshot.last_attempt_at)).join(
            Venue, Venue.id == VenueSnapshot.venue_id).where(Venue.provider_id == provider.id))
        if last_attempt and now < last_attempt + provider.min_request_interval_seconds * 1000:
            return snapshot
        if snapshot is None:
            start = datetime.combine(day, time(), ZoneInfo(venue.timezone))
            snapshot = VenueSnapshot(venue_id=venue.id, local_date=day.isoformat(), revision=0,
                content_hash='', slots=[], coverage={'starts_at': start.isoformat(),
                    'ends_at': (start + timedelta(days=1)).isoformat(), 'complete': False,
                    'identity_mode': 'court'}, last_attempt_at=now, next_poll_at=now)
            db.add(snapshot)
        snapshot.last_attempt_at = now
        snapshot.next_poll_at = now + provider.min_poll_seconds * 1000
        db.commit()  # Persist reservation before network I/O, including first failures.
        revision = credential_revision(provider)
        try:
            source = build_provider(provider.adapter_key, dict(provider.config), provider.credential_env)
            result = await source.fetch_day(venue.external_venue_id, day)
            if (result.external_venue_id != venue.external_venue_id or result.local_date != day
                    or result.timezone != venue.timezone or result.fetched_at.tzinfo is None
                    or result.fetched_at.timestamp() * 1000 > now_ms() + 5000):
                raise VenueSourceError('SOURCE_FORMAT_ERROR')
        except Exception as exc:
            snapshot.last_error_code = exc.code if isinstance(exc, VenueSourceError) else 'SOURCE_ERROR'
            if snapshot.last_error_code in AUTH_ERRORS:
                pause(provider, snapshot.last_error_code, revision)
            # Keep last successful data for inspection, but never mark it fresh.
            db.commit()
            return snapshot
        content = {'coverage': result.coverage.model_dump(mode='json'),
                   'slots': [slot.model_dump(mode='json') for slot in result.slots]}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        changed = snapshot.content_hash != digest
        if changed:
            snapshot.revision += 1
            snapshot.content_hash = digest
            snapshot.slots = content['slots']
            snapshot.coverage = content['coverage']
            db.add(Event(type='venue.changed', activity_id=None, resource_version=snapshot.revision,
                         payload={'venue_id': venue.id, 'local_date': day.isoformat(), 'revision': snapshot.revision}))
        verified(provider)
        snapshot.last_success_at = int(result.fetched_at.timestamp() * 1000)
        snapshot.last_error_code = None
        snapshot.reported_stale_at = None
        db.commit()
        return snapshot
