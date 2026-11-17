from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from .wakeup_client import fetch_share, WakeUpError


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
        match = re.search(r"(?<![A-Za-z0-9])[a-fA-F0-9]{32}(?![A-Za-z0-9])", share_text.strip())
        if not match: raise ValueError("没有找到有效的 WakeUp 分享口令")
        if not self.endpoint: return await fetch_share(match.group(0))
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(self.endpoint, json={"token": match.group(0)})
            response.raise_for_status(); return response.content

    def normalize(self, payload: bytes) -> NormalizedSchedule:
        try: data = json.loads(payload)
        except Exception as error: raise ValueError("课表响应不是有效 JSON") from error
        if isinstance(data, dict) and "shareData" in data:
            try: data = normalize_share(data["shareData"])
            except WakeUpError: raise
            except (KeyError, TypeError, ValueError, IndexError, OverflowError):
                raise WakeUpError("WAKEUP_INVALID_DATA", "课表包含不支持的周次、节次或时间设置，未导入任何课程。") from None
        required = {"provider_key", "label", "timezone", "term_start_monday", "term_end_date", "periods", "lessons"}
        if not required.issubset(data): raise ValueError("课表响应缺少必要字段")
        if data["provider_key"] != "wakeup": raise ValueError("课表来源不匹配")
        periods = {int(p["index"]): p for p in data["periods"]}
        for lesson in data["lessons"]:
            if not lesson.get("weeks") or not lesson.get("period_indices"): raise ValueError("课程缺少周次或节次")
            if any(int(index) not in periods for index in lesson["period_indices"]): raise ValueError("课程引用了未知节次")
        return NormalizedSchedule("wakeup", str(data["label"]), str(data["timezone"]), date.fromisoformat(data["term_start_monday"]), date.fromisoformat(data["term_end_date"]), data["periods"], data["lessons"], data.get("dated_occurrences", []), hashlib.sha256(payload).hexdigest())


def normalize_share(share):
    parts = [json.loads(line) for line in share.splitlines() if line.strip()]
    if len(parts) != 5: raise ValueError("sections")
    timetable, times, settings, courses, arrangements = parts
    if len(arrangements) > 1000: raise ValueError("too many lessons")
    start = datetime.strptime(settings["startDate"], "%Y-%m-%d").date()
    start -= timedelta(days=start.weekday())
    max_week = int(settings["maxWeek"])
    if not 1 <= max_week <= 53: raise ValueError("term length")
    definitions = {str(c["id"]): c for c in courses}
    table_id = timetable["id"]
    nodes = {int(p["node"]): p for p in times if p["timeTable"] == table_id}
    periods = {}; lessons = []
    def add_period(index, begin, end):
        a = datetime.strptime(begin, "%H:%M"); b = datetime.strptime(end, "%H:%M")
        if b <= a:
            label = f"第 {index} 节" if index < 10000 else "自定义课程"
            raise WakeUpError("WAKEUP_INVALID_TIME", f"{label}时间为 {begin}–{end}，结束时间必须晚于开始时间。请在 WakeUp 修正后重新分享。")
        periods[index] = {"index": index, "start": a.strftime("%H:%M"), "end": b.strftime("%H:%M")}
    for number, rule in enumerate(arrangements):
        key = str(rule["id"]); course = definitions[key]
        weekday = int(rule["day"]); first = int(rule["startWeek"]); last = int(rule["endWeek"])
        kind = int(rule["type"])
        if not (1 <= weekday <= 7 and 1 <= first <= last <= max_week and kind in (0, 1, 2)):
            raise ValueError("week settings")
        weeks = [w for w in range(first, last + 1) if kind == 0 or w % 2 == kind % 2]
        if not weeks: continue
        if rule.get("ownTime"):
            indices = [10000 + number]
            add_period(indices[0], rule["startTime"], rule["endTime"])
        else:
            node = int(rule["startNode"]); step = int(rule["step"])
            if not 1 <= node <= 100 or not 1 <= step <= 30: raise ValueError("nodes")
            indices = list(range(node, node + step))
            for index in indices:
                p = nodes[index]; add_period(index, p["startTime"], p["endTime"])
            if any(periods[a]["end"] > periods[b]["start"] for a, b in zip(indices, indices[1:])):
                raise ValueError("overlapping periods")
        lessons.append({"external_key": key, "preview_title": str(course["courseName"])[:200],
            "weekday": weekday, "weeks": weeks, "period_indices": indices})
    return {"provider_key": "wakeup", "label": str(settings.get("tableName") or "WakeUp课表")[:80],
        "timezone": "Asia/Shanghai", "term_start_monday": start.isoformat(),
        "term_end_date": (start + timedelta(weeks=max_week, days=-1)).isoformat(),
        "periods": list(periods.values()), "lessons": lessons, "dated_occurrences": []}


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
