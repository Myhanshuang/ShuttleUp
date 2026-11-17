from datetime import datetime
from zoneinfo import ZoneInfo

from shuttleup.availability.engine import Interval, Rule, resolve_availability, summarize_window

TZ = ZoneInfo("Asia/Shanghai")


def dt(value: str): return datetime.fromisoformat(value).replace(tzinfo=TZ)


def test_unknown_without_baseline_and_priority_restore():
    query = Interval(dt("2026-09-19T18:00"), dt("2026-09-19T22:00"))
    weekly = Rule("weekly", "free", "weekly", 1, recurrence={"weekdays": [6], "start_time": "18:00", "end_time": "22:00", "valid_from": "2026-09-01", "valid_until": "2026-10-01", "timezone": "Asia/Shanghai"})
    once = Rule("one_off", "busy", "once", 2, dt("2026-09-19T19:00"), dt("2026-09-19T20:00"))
    resolved = resolve_availability([weekly, once], query, "Asia/Shanghai")
    assert [s.state for s in resolved] == ["free", "busy", "free"]
    assert summarize_window(resolved, query) == "busy"
    assert resolve_availability([], query, "Asia/Shanghai")[0].state == "unknown"


def test_activity_override_beats_personal_rule():
    query = Interval(dt("2026-09-19T19:00"), dt("2026-09-19T20:00"))
    rules = [Rule("one_off", "busy", "once", 3, query.start, query.end), Rule("activity", "free", "once", 4, query.start, query.end)]
    assert summarize_window(resolve_availability(rules, query, "Asia/Shanghai"), query) == "free"



def test_weekly_rule_can_end_at_midnight():
    query = Interval(dt('2026-09-19T23:30'), dt('2026-09-20T00:00'))
    rule = Rule('weekly', 'free', 'weekly', 1, recurrence={'weekdays': [6], 'start_time': '23:30', 'end_time': '24:00', 'valid_from': '2026-09-19', 'valid_until': '2026-09-19'})
    assert summarize_window(resolve_availability([rule], query, 'Asia/Shanghai'), query) == 'free'


def test_uncertain_is_explicit_and_not_free_or_default_unknown():
    query = Interval(dt('2026-09-19T18:00'), dt('2026-09-19T20:00'))
    rule = Rule('one_off', 'uncertain', 'once', 1, query.start, query.end)
    assert summarize_window(resolve_availability([rule], query, 'Asia/Shanghai'), query) == 'uncertain'
    assert summarize_window(resolve_availability([], query, 'Asia/Shanghai'), query) == 'unknown'
