from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, model_validator


class VenueSourceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Coverage(BaseModel):
    starts_at: datetime
    ends_at: datetime
    complete: bool
    identity_mode: str = Field(pattern="^(court|aggregate)$")
    booking_constraints: dict = Field(default_factory=dict)


class VenueSlot(BaseModel):
    external_slot_id: str
    court_id: str | None
    court_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    status: str = Field(pattern="^(available|unavailable|not_released|unknown)$")
    price_cents: int | None = Field(default=None, ge=0)
    remaining_count: int = Field(default=0, ge=0)
    release_at: datetime | None = None
    booking_url: str | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.ends_at <= self.starts_at: raise ValueError("slot end must follow start")
        return self


class VenueDayResult(BaseModel):
    schema_version: int = 1
    external_venue_id: str
    local_date: date
    timezone: str
    fetched_at: datetime
    coverage: Coverage
    slots: list[VenueSlot]


class VenueProvider(Protocol):
    key: str
    async def list_venues(self) -> list[dict]: ...
    async def fetch_day(self, venue_external_id: str, local_date: date) -> VenueDayResult: ...
    async def health(self) -> dict: ...


class StandardJsonProvider:
    key = "standard_json"
    def __init__(self, endpoint: str, allowed_host: str, headers: dict[str, str] | None = None):
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or parsed.hostname != allowed_host: raise ValueError("endpoint must use configured HTTPS host")
        self.endpoint = endpoint; self.allowed_host = allowed_host; self.headers = headers or {}

    async def list_venues(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(f"{self.endpoint.rstrip('/')}/venues", headers=self.headers); response.raise_for_status(); return response.json()["items"]

    async def fetch_day(self, venue_external_id: str, local_date: date) -> VenueDayResult:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(f"{self.endpoint.rstrip('/')}/venues/{venue_external_id}/slots", params={"date": local_date.isoformat()}, headers=self.headers); response.raise_for_status()
        return VenueDayResult.model_validate(response.json())

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client: response = await client.get(f"{self.endpoint.rstrip('/')}/health", headers=self.headers)
            return {"status": "ok" if response.is_success else "error", "checked_at": datetime.now().astimezone().isoformat(), "message": f"HTTP {response.status_code}"}
        except httpx.HTTPError as error: return {"status": "error", "checked_at": datetime.now().astimezone().isoformat(), "message": type(error).__name__}


def build_provider(adapter_key: str, settings: dict, credential_env: str | None = None):
    import os
    if adapter_key == "standard_json":
        credential = os.getenv(credential_env) if credential_env else None
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        return StandardJsonProvider(settings["endpoint"], settings["allowed_host"], headers)
    from .local import extension_for
    extension = extension_for(adapter_key)
    if extension:
        return extension.providers[adapter_key](credential_env)
    raise VenueSourceError("ADAPTER_UNAVAILABLE")


def supported_provider(key):
    from .local import extension_for
    return key in ("manual", "standard_json") or extension_for(key) is not None


PROVIDER_REGISTRY = {"standard_json": StandardJsonProvider, "manual": None}

