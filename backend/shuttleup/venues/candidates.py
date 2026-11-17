from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo


def cover_court(slots: list[dict], court_id: str, start: datetime, end: datetime):
    edges: dict[datetime, list[dict]] = {}
    for slot in slots:
        slot_start = datetime.fromisoformat(slot["starts_at"]); slot_end = datetime.fromisoformat(slot["ends_at"])
        if slot.get("court_id") == court_id and slot.get("status") == "available" and slot_start >= start and slot_end <= end:
            edges.setdefault(slot_start, []).append(slot)
    best: dict[datetime, tuple[bool, int, list[dict]]] = {start: (False, 0, [])}
    for moment in sorted(edges):
        if moment not in best: continue
        for edge in edges[moment]:
            next_time = datetime.fromisoformat(edge["ends_at"])
            if next_time > end: continue
            prior_unknown, prior_price, path = best[moment]; unknown = prior_unknown or edge.get("price_cents") is None; price = prior_price + (edge.get("price_cents") or 0)
            candidate = (unknown, price, path + [edge]); existing = best.get(next_time)
            if existing is None or (candidate[0], candidate[1], [x["external_slot_id"] for x in candidate[2]]) < (existing[0], existing[1], [x["external_slot_id"] for x in existing[2]]): best[next_time] = candidate
    return best.get(end)


def allowed_window(activity, start, end):
    if "daily_windows" not in activity: return True
    local_start=start.astimezone(ZoneInfo(activity.get("timezone","Asia/Shanghai")))
    local_end=end.astimezone(local_start.tzinfo)
    if local_start.date()!=local_end.date(): return False
    return any(local_start.isoweekday() in w["weekdays"]
               and local_start.time()>=time.fromisoformat(w["start_time"])
               and local_end.time()<=time.fromisoformat(w["end_time"])
               for w in activity["daily_windows"])


def window_starts(activity, day, duration, now):
    if not day or "daily_windows" not in activity:return set()
    starts=set(); local_date=date.fromisoformat(day); tz=ZoneInfo(activity.get("timezone","Asia/Shanghai"))
    for w in activity["daily_windows"]:
        if local_date.isoweekday() not in w["weekdays"]:continue
        start=datetime.combine(local_date,time.fromisoformat(w["start_time"]),tz)
        end=datetime.combine(local_date,time.fromisoformat(w["end_time"]),tz)
        while start+duration<=end:
            if start>now:starts.add(start)
            start+=timedelta(minutes=15)
    return starts


def generate_candidates(activity: dict, people: list[dict], venue_days: list[dict], now: datetime) -> dict:
    candidates = []; others = []; duration = timedelta(minutes=activity["duration_minutes"])
    venue_order = {venue_id: index for index, venue_id in enumerate(activity.get("venue_preferences", []))}
    for venue_day in venue_days:
        slots = venue_day["slots"]; starts = sorted({datetime.fromisoformat(s["starts_at"]) for s in slots if s["status"] == "available" and datetime.fromisoformat(s["starts_at"]) > now})
        starts=sorted(set(starts) | window_starts(activity,venue_day.get("local_date"),duration,now))
        for start in starts:
            end = start + duration
            if not allowed_window(activity,start,end):continue
            eligible = [p["id"] for p in people if p["state_for"](start, end) == "free"]
            busy = [p["id"] for p in people if p["state_for"](start, end) == "busy"]
            uncertain = [p["id"] for p in people if p["state_for"](start, end) == "uncertain"]
            unknown = [p["id"] for p in people if p["id"] not in eligible and p["id"] not in busy and p["id"] not in uncertain]
            required_missing = [p["id"] for p in people if p.get("required") and p["id"] not in eligible]
            mode = venue_day["coverage"].get("identity_mode")
            covered = []
            if mode == "court" and venue_day.get("fresh", False):
                for court_id in sorted({s.get("court_id") for s in slots if s.get("court_id")}):
                    path = cover_court(slots, court_id, start, end)
                    if path: covered.append((court_id, path))
            covered.sort(key=lambda item: (item[1][0], item[1][1], item[0])); chosen = covered[:activity["court_count"]]
            verified = sum(bool(p.get("required")) for p in people) <= activity["max_players"] and len(eligible) >= activity["min_players"] and not required_missing and len(chosen) >= activity["court_count"]
            if verified: classification = "verified"
            elif sum(bool(p.get("required")) for p in people) > activity["max_players"]: classification = "too_many_required"
            elif len(eligible) < activity["min_players"] or required_missing: classification = "insufficient_players"
            elif mode == "aggregate": classification = "needs_court_check"
            else: classification = "people_only"
            prices_unknown = any(path[0] for _, path in chosen); total_price = None if prices_unknown or len(chosen) < activity["court_count"] else sum(path[1] for _, path in chosen)
            fingerprint_data = [activity["version"], venue_day["venue_id"], start.isoformat(), end.isoformat(), [[cid, [s["external_slot_id"] for s in path[2]]] for cid,path in chosen]]
            fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
            candidate = {"id": f"cnd_{fingerprint[:12]}", "short_code": fingerprint[:4].upper(), "fingerprint": fingerprint, "classification": classification, "starts_at": start.isoformat(), "ends_at": end.isoformat(), "venue_id": venue_day["venue_id"], "venue_name": venue_day["venue_name"], "court_ids": [x[0] for x in chosen], "continuous_court_count": len(covered), "eligible_participant_ids": eligible, "unknown_participant_ids": unknown, "uncertain_participant_ids": uncertain, "busy_participant_ids": busy, "missing_required_participant_ids": required_missing, "total_price_cents": total_price, "last_success_at": venue_day.get("last_success_at"), "fresh_until": venue_day.get("fresh_until"), "reason_codes": (["MIN_PLAYERS_MET"] if len(eligible)>=activity["min_players"] else []) + (["REQUIRED_PLAYERS_FREE"] if not required_missing else []) + (["COURTS_CONTINUOUS"] if len(chosen)>=activity["court_count"] else [])}
            (candidates if verified else others).append(candidate)
    def order(c): return (-min(len(c["eligible_participant_ids"]), activity["max_players"]), venue_order.get(c["venue_id"], 9999), c["total_price_cents"] is None, c["total_price_cents"] or 0, c["starts_at"], c["venue_id"])
    return {"candidates": sorted(candidates, key=order), "other_windows": sorted(others, key=order)}

