"""AstrBot is a public interaction channel, acting as the message sender.

Business mutations invoke the same validated handlers as Web. Their commits are
flushed here so the command result and its mutations share one idempotent commit.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Response
from sqlalchemy import select

from ..activities import routes as activities, workflow_routes as workflow
from ..activities.schemas import ActivityCreate, JoinRequest
from ..activities.service import participant_for, require_member
from ..auth.service import HelperRequest
from ..availability import routes as availability
from ..billing import routes as billing
from ..models import Activity, BotActivityLink, BotContext, BotIdentity, OneTimeToken, Participant, PaymentClaim, User, now_ms
from ..security import invite_token, token_hash


class AtomicSession:
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def commit(self):
        self.session.flush()


def invalid(message, status=422, code="VALIDATION_ERROR"):
    raise HTTPException(status, detail={"code": code, "message": message})


def link_context(db, body, activity):
    context = db.scalar(select(BotContext).where(BotContext.bot_key == body.bot_key, BotContext.umo == body.umo))
    if not context:
        context = BotContext(bot_key=body.bot_key, umo=body.umo, label="私聊" if body.is_private else "球友群")
        db.add(context)
        db.flush()
    context.current_activity_id = activity.id
    if not db.scalar(select(BotActivityLink).where(BotActivityLink.context_id == context.id, BotActivityLink.activity_id == activity.id)):
        db.add(BotActivityLink(context_id=context.id, activity_id=activity.id))
    return context


async def dispatch(body, db, key):
    from .routes import reply
    cmd, args = body.command, body.args
    if cmd == "help":
        return reply("@我发送 /绑定身份 昵称，为当前 QQ 绑定身份；也可以直接 /发起约球 周末夜场，无需网页注册。随后用 /羽球 加入、有空、推荐、选择、参加、已订、到场、记账、账单、已付、收款、结束、结算。私聊 /羽球 网页 可在网页继续同一身份。")
    identity = db.scalar(select(BotIdentity).where(BotIdentity.bot_key == body.bot_key, BotIdentity.platform_id == body.platform_id, BotIdentity.sender_id == body.sender_id))
    if cmd == "identity.bind":
        if not body.is_private:
            invalid("账号绑定请私聊 Bot 执行。", code="PRIVATE_REQUIRED")
        token = db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == token_hash(str(args.get("code", ""))), OneTimeToken.purpose == "bot_bind", OneTimeToken.consumed_at.is_(None), OneTimeToken.expires_at > now_ms()))
        if not token:
            invalid("绑定码无效或已过期。", code="INVALID_BIND_CODE")
        if identity and identity.user_id != token.user_id:
            invalid("此平台身份已有独立数据。请用私聊 /羽球 网页 登录该身份；暂不支持合并两个已有身份。", 409, "IDENTITY_EXISTS")
        if not identity:
            identity = BotIdentity(bot_key=body.bot_key, platform_id=body.platform_id, sender_id=body.sender_id, user_id=token.user_id)
            db.add(identity)
        identity.private_umo = body.umo
        token.consumed_at = now_ms()
        return reply("已绑定网页账号，两端使用同一身份。", "/me")
    existing_identity = identity is not None
    requested_name = args.get("display_name") if cmd == "identity.create" else None
    if requested_name is not None and (not isinstance(requested_name, str) or not requested_name.strip() or len(requested_name) > 40):
        invalid("昵称需要 1–40 个字符。")
    if not identity:
        user = User(display_name=requested_name.strip() if requested_name else body.sender_name.strip() or "球友")
        db.add(user)
        db.flush()
        identity = BotIdentity(bot_key=body.bot_key, platform_id=body.platform_id, sender_id=body.sender_id, user_id=user.id)
        db.add(identity)
        db.flush()
    user = db.get(User, identity.user_id)
    request = HelperRequest(user.id)
    if body.is_private:
        identity.private_umo = body.umo
    if cmd == "identity.create":
        return reply(f"{'当前 QQ 已绑定' if existing_identity else '已为当前 QQ 绑定'}身份「{user.display_name}」。之后发起、加入和记账都会使用这个身份。私聊 /羽球 网页 可在网页继续，并在个人设置中设置登录账号。")
    if cmd == "web.open":
        if not body.is_private:
            return reply("请私聊我发送 /羽球 网页，获取属于你的一次性网页登录链接。")
        from ..security import token as random_token
        raw = random_token()
        db.add(OneTimeToken(token_hash=token_hash(raw), purpose="bot_login", user_id=user.id, expires_at=now_ms()+600000))
        return reply("使用此链接在网页继续你的活动。链接 10 分钟内有效且只能使用一次，请勿转发。", f"/bot-login#token={raw}")
    context = db.scalar(select(BotContext).where(BotContext.bot_key == body.bot_key, BotContext.umo == body.umo))
    if cmd == "context.bind":
        token = db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == token_hash(str(args.get("code", ""))), OneTimeToken.purpose == "group_bind", OneTimeToken.consumed_at.is_(None), OneTimeToken.expires_at > now_ms()))
        if not token:
            invalid("群关联码无效或已过期。")
        activity = db.get(Activity, token.activity_id)
        activities.require_host(activity, user)
        link_context(db, body, activity)
        token.consumed_at = now_ms()
        return reply(f"已关联 {activity.short_code} · {activity.title}。", f"/a/{activity.id}")
    if cmd == "activity.create":
        data = await activities.create_activity(ActivityCreate(**{k: v for k, v in args.items() if k in ActivityCreate.model_fields}), request, db)
        activity = db.get(Activity, data["id"])
        link_context(db, body, activity)
        return reply(f"已发起 {activity.title}（{activity.short_code}），你是主持人。当前会话已关联，球友发送 /羽球 加入 即可参与，再用 /羽球 有空 日期 18:00-20:00 填时间。", f"/a/{activity.id}")
    if cmd == "activity.list":
        if context:
            items = db.scalars(select(Activity).join(BotActivityLink).where(BotActivityLink.context_id == context.id)).all()
            return reply("当前会话活动：\n" + "\n".join(f"{a.short_code} · {a.title} · {activities.activity_dto(db, a, user)['status_label']}" for a in items) if items else "当前会话还没有活动，发送 /发起约球 开始。")
        data = await activities.list_activities(request, db=db)
        return reply("你的活动：\n" + "\n".join(f"{a['short_code']} · {a['title']}" for a in data["items"]) if data["items"] else "还没有活动，发送 /发起约球 开始。")
    if cmd == "schedule.open":
        return reply("在网页时间表拖选或导入课表；私聊 /羽球 网页 可登录同一身份。", "/me/time")
    if cmd == "availability.set" and args.get("personal"):
        return await set_availability(body, db, request, user, None)
    activity = db.scalar(select(Activity).where(Activity.short_code == body.activity_code.upper())) if body.activity_code else db.get(Activity, context.current_activity_id) if context and context.current_activity_id else None
    if not activity:
        return reply("没有找到当前活动。发送 /发起约球 创建，或用 --活动 活动短号 指定。")
    linked = context and db.scalar(select(BotActivityLink).where(BotActivityLink.context_id == context.id, BotActivityLink.activity_id == activity.id))
    if not body.is_private and not linked:
        invalid("该活动没有关联到当前群。请让主持人关联活动。", 403, "FORBIDDEN")
    if cmd == "participant.join":
        if not linked:
            invalid("请通过活动邀请或在活动所在群加入。", 403, "FORBIDDEN")
        if activity.status not in ("collecting", "booking", "confirmed"):
            invalid("已结束或取消的活动不能加入。", 409, "INVALID_TRANSITION")
        membership = db.scalar(select(Participant).where(Participant.activity_id == activity.id, Participant.user_id == user.id))
        if membership and membership.membership == "active":
            return reply(f"你已加入 {activity.title}。", f"/a/{activity.id}")
        return reply("加入前请在邀请页填写本次空闲时间；私聊 /羽球 网页 可登录同一身份。",
            f"/i/{invite_token(activity.id, activity.invite_nonce)}")
    mine = require_member(db, activity, user)
    path = f"/a/{activity.id}"
    if cmd == "activity.current":
        return reply(f"{activity.short_code} · {activity.title} · {activities.activity_dto(db, activity, user)['status_label']}\n{activity.date_from} 至 {activity.date_to}", path)
    if cmd == "activity.switch":
        activities.require_host(activity, user)
        if not linked:
            invalid("活动尚未关联到当前会话。", 403, "FORBIDDEN")
        context.current_activity_id = activity.id
        return reply(f"当前活动已切换为 {activity.title}。", path)
    if cmd == "participant.leave":
        await activities.leave(activity.id, request, db)
        return reply(f"已退出 {activity.title}。")
    if cmd == "availability.set":
        return await set_availability(body, db, request, user, activity)
    if cmd == "rsvp.set":
        await workflow.rsvp(activity.id, workflow.RsvpRequest(plan_id=activity.current_plan_id or "", response=args.get("response")), request, db)
        return reply("已确认参加。" if args["response"] == "yes" else "已记录不参加。", path)
    if cmd == "attendance.set":
        await workflow.attendance(activity.id, workflow.AttendanceRequest(entries=[{"participant_id": mine.id, "state": args.get("state")}]), request, db)
        return reply("已记录你的到场状态，出账前由主持人核对。", path)
    if cmd in ("candidate.list", "venue.list", "plan.open_select"):
        from ..venues.routes import compute_candidates
        candidates = compute_candidates(db, activity, 100)["candidates"]
        if cmd == "plan.open_select":
            index = int(args.get("index", 0)) - 1
            if not 0 <= index < len(candidates):
                invalid("先发送 /羽球 推荐，再用 /羽球 选择 序号 选择当前方案。")
            c = candidates[index]
            ps = db.scalars(select(Participant).where(Participant.activity_id == activity.id, Participant.membership == "active")).all()
            roster = sorted([p for p in ps if p.id in c["eligible_participant_ids"]], key=lambda p: (not p.required, p.join_order))[:activity.max_players]
            await workflow.select_plan(activity.id, workflow.SelectPlan(candidate_id=c["id"], roster_participant_ids=[p.id for p in roster], expected_version=activity.version), request, db)
            return reply("方案已选择。请球友确认参加，主持人完成预约后发送 /羽球 已订 场地号。", path)
        return reply("当前推荐（选择时会重新检查）：\n" + "\n".join(f"{i+1}. {datetime.fromisoformat(c['starts_at']).astimezone(ZoneInfo(activity.timezone)):%m-%d %H:%M} · {c['venue_name']} · {len(c['eligible_participant_ids'])} 人可来" for i, c in enumerate(candidates[:10])) if candidates else "暂无满足人数、空闲时间和场地条件的方案。", path)
    if cmd == "booking.open_create":
        data = activities.activity_dto(db, activity, user)
        plan = data["current_plan"]
        if not plan or not args.get("court"):
            invalid("先选择方案并实际订场，再发送 /羽球 已订 场地号 [订单号]。")
        await workflow.record_booking(activity.id, workflow.BookingCreate(venue_id=plan["venue_id"], court_ids=str(args["court"]).replace("，", ",").split(","), starts_at=plan["starts_at"], ends_at=plan["ends_at"], booker_participant_id=mine.id, external_order_no=args.get("order"), expected_version=activity.version), request, db)
        return reply("已登记订场；实际支出请用 /羽球 记账 场地 金额 记录。", path)
    if cmd in ("activity.open_finish", "activity.open_cancel"):
        if cmd == "activity.open_finish":
            await workflow.finish(activity.id, workflow.VersionRequest(expected_version=activity.version), request, db)
        else:
            await workflow.cancel(activity.id, workflow.CancelRequest(expected_version=activity.version, reason=args.get("reason", "")), request, db)
        return reply("活动已结束，请核对到场并结算。" if cmd == "activity.open_finish" else "活动已取消，请处理实际费用。", path)
    if cmd == "expense.create":
        raw_kind, value = str(args.get("kind")), str(args.get("value", ""))
        quantity = unit = None
        if raw_kind == "球":
            quantity = int(value.removesuffix("个")); unit = activity.price_defaults.get("shuttle_unit_cents")
            if unit is None:
                invalid("还未设置球单价，请用 /羽球 记账 球费 金额。")
            cents = quantity * unit
        else:
            cents = int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        data = await billing.create_expense(activity.id, billing.ExpenseCreate(kind="venue" if raw_kind == "场地" else "shuttle" if raw_kind in ("球", "球费") else "extra", description=args.get("description") or raw_kind, amount_cents=cents, payer_participant_id=mine.id, quantity=quantity, unit_price_cents=unit), request, key, db)
        return reply(f"已记录 ¥{cents/100:.2f}，垫付人：{user.display_name}。费用编号 {data['short_code']}。", path + "/bill")
    if cmd == "bill.open_publish":
        await billing.publish_bill(activity.id, billing.PublishRequest(expected_generation=activity.bill_generation), request, key, db)
        return reply("账单已发布。球友可私聊查看各自付款任务。", path + "/bill")
    if cmd == "bill.show":
        if not body.is_private:
            return reply(f"请私聊 /羽球 账单 --活动 {activity.short_code} 查看你的账款。")
        data = await billing.get_bill(activity.id, request, db=db)
        lines = [f"{activity.title} · 我的账款 ¥{data['my_summary']['balance_cents']/100:.2f}（正数应收，负数应付）"]
        lines += [f"付款任务 {t['short_code']} · 剩余 ¥{t['remaining_cents']/100:.2f}" for t in data["my_summary"]["outgoing"]]
        lines += [f"待确认收款 {p['short_code']} · ¥{p['amount_cents']/100:.2f}" for p in data["payment_claims"] if p["status"] == "claimed" and any(t["id"] == p["transfer_id"] for t in data["my_summary"]["incoming"])]
        return reply("\n".join(lines), path + "/bill")
    if cmd == "payment.confirm":
        claim = db.scalar(select(PaymentClaim).where(PaymentClaim.activity_id == activity.id, PaymentClaim.short_code == str(args.get("code", "")).upper()))
        if not claim:
            invalid("没有找到付款声明。")
        await billing.confirm_payment(activity.id, claim.id, request, key, db)
        return reply("已确认收款。", path + "/bill")
    if cmd == "payment.claim":
        data = await billing.get_bill(activity.id, request, db=db)
        transfer = next((t for t in data["my_summary"]["outgoing"] if t["short_code"] == str(args.get("code", "")).upper()), None)
        if not transfer:
            invalid("没有找到你的待付款任务。")
        amount = int((Decimal(str(args["amount"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if args.get("amount") is not None else transfer["remaining_cents"]
        result = await billing.claim_payment(activity.id, billing.ClaimRequest(bill_revision_id=data["id"], transfer_id=transfer["id"], amount_cents=amount), request, key, db)
        return reply(f"已提交付款声明 {result['short_code']}，等待收款人确认。", path + "/bill")
    if cmd in ("availability.summary", "expense.open_split"):
        return reply("查看时间汇总。" if cmd == "availability.summary" else "请在网页设置指定分摊。", path if cmd == "availability.summary" else path + "/bill")
    invalid("未知指令，请发送 /羽球 帮助。")


async def set_availability(body, db, request, user, activity):
    from .routes import reply
    args = body.args
    start, end = str(args.get("time", "")).split("-", 1)
    zone = ZoneInfo(activity.timezone if activity else user.timezone)
    day = str(args.get("date", ""))
    rule = availability.RuleCreate(state=args.get("state"), source="activity" if activity else "one_off", kind="once", activity_id=activity.id if activity else None, start_at=datetime.fromisoformat(f"{day}T{start}").replace(tzinfo=zone), end_at=datetime.fromisoformat(f"{day}T{end}").replace(tzinfo=zone))
    await availability.create_rules(availability.RulesCreate(rules=[rule], expected_revision=user.availability_revision), request, db)
    state_label = {"free": "空闲", "busy": "繁忙", "uncertain": "不确定", "unknown": "未知"}[rule.state]
    return reply(f"已标记 {day} {start}–{end} 为{state_label}（{'仅本次活动' if activity else '个人时间'}）。", f"/me/time?activity_id={activity.id}" if activity else "/me/time")
