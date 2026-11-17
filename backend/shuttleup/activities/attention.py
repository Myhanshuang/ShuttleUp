"""The viewer's actionable next step, shared by the list and activity pages."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select

from ..availability.engine import Interval, resolve_availability
from ..models import AvailabilityRule, BillRevision, Participant, PaymentClaim, now_ms


def attention(db, activity, viewer, mine, plan):
    url = f"/a/{activity.id}"
    def step(label, detail, needed=False, href=url):
        return {"label": label, "detail": detail, "needed": needed, "href": href}
    if not mine or mine.membership != "active":
        return step("已离开活动", "需要主持人恢复成员身份后才能继续参与。")
    host = activity.host_user_id == viewer.id
    people = db.scalars(select(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active")).all()
    if activity.status == "collecting":
        from ..availability.routes import to_rule
        tz = ZoneInfo(activity.timezone)
        start = datetime.combine(datetime.fromisoformat(activity.date_from).date(), time.min, tz)
        end = datetime.combine(datetime.fromisoformat(activity.date_to).date() + timedelta(days=1), time.min, tz)
        filled = set()
        for p in people:
            rows = db.scalars(select(AvailabilityRule).where(AvailabilityRule.user_id == p.user_id,
                (AvailabilityRule.activity_id.is_(None)) | (AvailabilityRule.activity_id == activity.id))).all()
            segments = resolve_availability([to_rule(r) for r in rows], Interval(start, end), activity.timezone)
            day = start
            while day < end and p.id not in filled:
                for w in activity.daily_windows:
                    if day.isoweekday() not in w["weekdays"]: continue
                    left = datetime.combine(day.date(), time.fromisoformat(w["start_time"]), tz)
                    right = datetime.combine(day.date(), time.fromisoformat(w["end_time"]), tz)
                    if any(s.state != "unknown" and s.span.start < right and s.span.end > left for s in segments):
                        filled.add(p.id); break
                day += timedelta(days=1)
        missing = len(people) - len(filled)
        if mine.id not in filled:
            return step("填写本次空闲时间", "请标记活动时段内何时空闲、繁忙或不确定。", True, f"/me/time?activity_id={activity.id}")
        if host and not activity.venue_preferences:
            return step("选择活动场馆", "你已填写时间；选好场馆后才能匹配连续球场。", True, url + "#activity-settings")
        if host:
            return step("查看方案与填写进度", f"还有 {missing} 人未填写活动时段内的时间。" if missing else "所有成员都有时间记录，可检查共同空闲和场地。", True, url + "#candidates")
        return step("你已填写，等待主持人选场", f"还有 {missing} 人未填写；你可以继续调整自己的时间。" if missing else "所有成员都有时间记录，等待主持人选择方案。")
    if activity.status in ("booking", "confirmed"):
        included = bool(plan and mine.id in plan.roster_participant_ids)
        if included and mine.rsvp == "pending":
            return step("确认是否参加", "方案已选定，请确认自己的安排。", True, url + "#selected-plan")
        if activity.status == "booking":
            if host: return step("完成预约并登记订场", "选定方案尚未订场。请完成场馆预约，再登记实际订单。", True, url + "#selected-plan")
            return step("等待主持人完成订场" if included else "查看本次参加名单", "你已回应，订场结果将在活动内更新。" if included else "你未进入当前拟参加名单，可联系主持人协调。")
        if host and plan and now_ms() >= plan.ends_at:
            return step("结束活动并核对到场", "活动时段已结束，请核对实际到场，再发布账单。", True, url + "#selected-plan")
        if included and mine.attendance == "unknown" and plan and now_ms() >= plan.starts_at:
            return step("登记我的到场情况", "到场或缺席后请更新记录，便于后续分摊。", True, url + "#selected-plan")
        return step("查看上场安排", "场地已确认，请按约定时间上场。" if included else "你未进入当前名单，可查看本场安排。")
    bill_url = url + "/bill"
    if activity.billing_status == "settled":
        return step("查看已结清账单", "活动已取消，已发生费用已结清。" if activity.status == "cancelled" else "本次活动和结算均已完成。", False, bill_url)
    if activity.billing_status == "draft":
        return step("核对到场与费用" if host else "等待主持人发布账单",
            "活动已取消，请处理已发生费用。" if activity.status == "cancelled" else "打球已结束，按实际到场核对费用。", host, bill_url)
    claims = db.scalars(select(PaymentClaim).where(PaymentClaim.bill_revision_id == activity.current_bill_id)).all()
    if any(c.to_participant_id == mine.id and c.status == "claimed" for c in claims):
        return step("确认收款", "有成员声明已付款，请核实到账。", True, bill_url)
    bill = db.get(BillRevision, activity.current_bill_id)
    waiting = False
    for t in bill.snapshot.get("transfers", []) if bill else []:
        related = [c for c in claims if c.transfer_id == t["id"]]
        remaining = t["amount_cents"] - sum(c.amount_cents for c in related if c.status == "confirmed")
        if t["from_participant_id"] == mine.id and remaining > 0:
            if any(c.status == "claimed" for c in related):
                waiting = True
                continue
            return step("处理本次付款", "核对账单后转账，并在活动内声明已付款。", True, bill_url)
    if waiting:
        return step("等待对方确认收款", "你已声明付款，对方确认后会更新结算状态。", False, bill_url)
    return step("查看结算进度", "当前没有需要你处理的收付款，等待其他成员结清。", False, bill_url)
