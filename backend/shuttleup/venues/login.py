"""Credential lifecycle shared by optional local venue adapters."""
import hashlib
import os
from sqlalchemy import select
from ..models import Venue, VenueSnapshot, now_ms
from .local import extension_for

AUTH_ERRORS = {'AUTH_REQUIRED', 'AUTH_EXPIRED', 'AUTH_REJECTED', 'CREDENTIAL_PERMISSIONS'}


def credential_revision(provider):
    extension = extension_for(provider.adapter_key)
    if extension and hasattr(extension, 'credential_revision'):
        return extension.credential_revision(provider.credential_env)
    value = os.getenv(provider.credential_env or '', '')
    return hashlib.sha256(value.encode()).hexdigest()


def paused(provider):
    return bool(provider.config.get('_login_state', {}).get('paused'))


def blocked(provider):
    state = provider.config.get('_login_state', {})
    return state.get('paused') and state.get('failed_revision') == credential_revision(provider)


def pause(provider, code, revision):
    state = dict(provider.config.get('_login_state', {}))
    state.update(paused=True, error=code, failed_revision=revision, failed_at=now_ms())
    provider.config = {**provider.config, '_login_state': state}


def verified(provider):
    provider.config = {**provider.config, '_login_state': {
        'paused': False, 'error': None, 'last_verified_at': now_ms()}}


def resume(db, provider):
    verified(provider)
    ids = select(Venue.id).where(Venue.provider_id == provider.id)
    for snapshot in db.scalars(select(VenueSnapshot).where(VenueSnapshot.venue_id.in_(ids))):
        snapshot.next_poll_at = 0
        snapshot.last_error_code = 'REFRESH_PENDING'


def status(provider):
    state = provider.config.get('_login_state', {})
    extension = extension_for(provider.adapter_key)
    job = extension.login_status() if extension and hasattr(extension, 'login_status') else None
    return {'supported': bool(extension and hasattr(extension, 'start_login')),
            'paused': bool(state.get('paused')), 'error': state.get('error'),
            'last_verified_at': state.get('last_verified_at'), 'job': job}
