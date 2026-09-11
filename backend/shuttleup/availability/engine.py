from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

AvailabilityState = Literal["free", "busy", "unknown"]
PRIORITY = {"baseline": 0, "course": 10, "weekly": 20, "one_off": 30, "activity": 40}


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Rule:
    source: str
    state: AvailabilityState
    kind: str
    edit_seq: int
    start: datetime | None = None
    end: datetime | None = None
    recurrence: dict | None = None
    id: str | None = None


@dataclass(frozen=True)
class ResolvedSegment:
    span: Interval
    state: AvailabilityState
    source: str | None


def _weekly_intervals(rule: Rule, query: Interval, timezone: str):
    rec = rule.recurrence or {}; tz = ZoneInfo(rec.get("timezone", timezone))
    local_start = query.start.astimezone(tz).date(); local_end = query.end.astimezone(tz).date()
    valid_from = date.fromisoformat(rec.get("valid_from", local_start.isoformat()))
    valid_until = date.fromisoformat(rec.get("valid_until", local_end.isoformat()))
    current = max(local_start, valid_from); final = min(local_end, valid_until)
    while current <= final:
        if current.isoweekday() in rec.get("weekdays", []):
            start = datetime.combine(current, time.fromisoformat(rec["start_time"]), tz)
            end = datetime.combine(current, time.fromisoformat(rec["end_time"]), tz)
            if end > start: yield Interval(start, end)
        current += timedelta(days=1)


def resolve_availability(rules: list[Rule], query: Interval, timezone: str) -> list[ResolvedSegment]:
    if query.end <= query.start or query.start.tzinfo is None or query.end.tzinfo is None:
        raise ValueError("query must be a non-empty aware interval")
    expanded: list[tuple[Rule, Interval]] = []
    for rule in rules:
        spans = [Interval(rule.start, rule.end)] if rule.kind == "once" and rule.start and rule.end else list(_weekly_intervals(rule, query, timezone))
        for span in spans:
            start, end = max(span.start, query.start), min(span.end, query.end)
            if start < end: expanded.append((rule, Interval(start, end)))
    boundaries = sorted({query.start, query.end, *(s.start for _, s in expanded), *(s.end for _, s in expanded)})
    result: list[ResolvedSegment] = []
    for start, end in zip(boundaries, boundaries[1:]):
        matching = [r for r, span in expanded if span.start <= start and span.end >= end]
        chosen = max(matching, key=lambda r: (PRIORITY[r.source], r.edit_seq)) if matching else None
        segment = ResolvedSegment(Interval(start, end), chosen.state if chosen else "unknown", chosen.source if chosen else None)
        if result and result[-1].state == segment.state and result[-1].source == segment.source:
            previous = result[-1]; result[-1] = ResolvedSegment(Interval(previous.span.start, end), previous.state, previous.source)
        else: result.append(segment)
    return result


def summarize_window(resolved: list[ResolvedSegment], query: Interval) -> AvailabilityState:
    covered = [s for s in resolved if s.span.start < query.end and s.span.end > query.start]
    if any(s.state == "busy" for s in covered): return "busy"
    if covered and covered[0].span.start <= query.start and covered[-1].span.end >= query.end and all(s.state == "free" for s in covered): return "free"
    return "unknown"

