from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


@dataclass(frozen=True)
class NormalizedSchedule:
    provider_key: str
    label: str
    timezone: str
    term_start_monday: date
    term_end_date: date
    periods: list[dict]
    lessons: list[dict]
    dated_occurrences: list[dict]
    payload_hash: str


class WakeUpImporter:
    key = "wakeup"

    def __init__(self, endpoint: str | None = None): self.endpoint = endpoint

    async def fetch(self, share_text: str) -> bytes:
        match = re.search(r"(?:口令[:：]?\s*)?([A-Za-z0-9_-]{6,64})", share_text.strip())
        if not match: raise ValueError("没有找到有效的 WakeUp 分享口令")
        if not self.endpoint: raise RuntimeError("WAKEUP_ENDPOINT_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(self.endpoint, json={"token": match.group(1)})
            response.raise_for_status(); return response.content

    def normalize(self, payload: bytes) -> NormalizedSchedule:
        try: data = json.loads(payload)
        except Exception as error: raise ValueError("课表响应不是有效 JSON") from error
        required = {"provider_key", "label", "timezone", "term_start_monday", "term_end_date", "periods", "lessons"}
        if not required.issubset(data): raise ValueError("课表响应缺少必要字段")
        if data["provider_key"] != "wakeup": raise ValueError("课表来源不匹配")
        periods = {int(p["index"]): p for p in data["periods"]}
        for lesson in data["lessons"]:
            if not lesson.get("weeks") or not lesson.get("period_indices"): raise ValueError("课程缺少周次或节次")
            if any(int(index) not in periods for index in lesson["period_indices"]): raise ValueError("课程引用了未知节次")
        return NormalizedSchedule("wakeup", str(data["label"]), str(data["timezone"]), date.fromisoformat(data["term_start_monday"]), date.fromisoformat(data["term_end_date"]), data["periods"], data["lessons"], data.get("dated_occurrences", []), hashlib.sha256(payload).hexdigest())


def expand_occurrences(schedule: NormalizedSchedule) -> list[dict]:
    period_map = {int(p["index"]): p for p in schedule.periods}; tz = ZoneInfo(schedule.timezone); result = []
    for lesson in schedule.lessons:
        for week in sorted(set(int(w) for w in lesson["weeks"])):
            day = schedule.term_start_monday + timedelta(weeks=week-1, days=int(lesson["weekday"])-1)
            if day > schedule.term_end_date: continue
            for index in sorted(set(int(i) for i in lesson["period_indices"])):
                period = period_map[index]
                start = datetime.combine(day, datetime.strptime(period["start"], "%H:%M").time(), tz)
                end = datetime.combine(day, datetime.strptime(period["end"], "%H:%M").time(), tz)
                result.append({"starts_at": start.isoformat(), "ends_at": end.isoformat(), "preview_title": lesson.get("preview_title", "课程")})
    for item in schedule.dated_occurrences:
        result.append({"starts_at": datetime.fromisoformat(item["starts_at"]).isoformat(), "ends_at": datetime.fromisoformat(item["ends_at"]).isoformat(), "preview_title": item.get("preview_title", "临时课程")})
    return sorted(result, key=lambda item: item["starts_at"])

