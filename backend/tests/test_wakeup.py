from pathlib import Path
import json

import httpx
import pytest

from shuttleup.availability.wakeup import WakeUpImporter, expand_occurrences


@pytest.mark.asyncio
async def test_share_message_extracts_code_instead_of_app_name(monkeypatch):
    token = "0123456789abcdef0123456789abcdef"
    def handler(request):
        assert json.loads(request.content) == {"token": token}
        return httpx.Response(200, content=b"{}")
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    payload = await WakeUpImporter("https://adapter.example/import").fetch(
        f"这是来自「WakeUp课程表」的课表分享，分享口令为「{token}」")
    assert payload == b"{}"


@pytest.mark.asyncio
async def test_share_message_without_code_is_rejected():
    with pytest.raises(ValueError, match="分享口令"):
        await WakeUpImporter().fetch("这是来自「WakeUp课程表」的课表分享")


def test_normalize_odd_even_weeks_and_period_gaps():
    payload = (Path(__file__).parent / "fixtures/wakeup-normalized.json").read_bytes()
    schedule = WakeUpImporter().normalize(payload); occurrences = expand_occurrences(schedule)
    odd = [o for o in occurrences if o["starts_at"].startswith(("2026-09-09", "2026-09-23"))]
    assert len(odd) == 4
    assert odd[0]["ends_at"].endswith("08:45:00+08:00")
    assert odd[1]["starts_at"].endswith("08:55:00+08:00")
    assert any(o["starts_at"].startswith("2026-09-18") for o in occurrences)
    assert any(o["starts_at"].startswith("2026-09-26") for o in occurrences)
