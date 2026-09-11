import asyncio
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..activities.service import emit, participant_for, require_host
from ..auth.service import require_csrf, require_user
from ..common import short_code
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import Activity, AvailabilityRule, BillRevision, BotActivityLink, BotContext, BotIdentity, Expense, Notification, OneTimeToken, Participant, PaymentClaim, User, now_ms
from ..security import token_hash

web_router=APIRouter(tags=["bot-bindings"])
bot_router=APIRouter(tags=["bot"])


class CommandRequest(BaseModel):
    bot_key: str
    platform_id: str
    sender_id: str
    umo: str
    message_id: str
    command: str
    activity_code: str|None=None
    args: dict=Field(default_factory=dict)


class DeliveryResult(BaseModel): lease_token: str; platform_message_id: str|None=None; error: str|None=None


def make_bind_token(db: Session,purpose: str,user_id: str|None=None,activity_id: str|None=None):
    raw="".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
    db.add(OneTimeToken(token_hash=token_hash(raw),purpose=purpose,user_id=user_id,activity_id=activity_id,expires_at=now_ms()+600000)); db.commit(); return {"code":raw,"expires_in":600}


@web_router.post("/me/bot-bind-token",status_code=201)
async def account_bind_token(request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); return make_bind_token(db,"bot_bind",user_id=user.id)


@web_router.post("/activities/{activity_id}/bot-bind-token",status_code=201)
async def group_bind_token(activity_id: str,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id)
    if not activity: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"活动不存在。"})
    require_host(activity,user); return make_bind_token(db,"group_bind",user_id=user.id,activity_id=activity.id)


def bot_auth(authorization: str|None,body_key: str|None=None):
    expected=get_settings().astrbot_main_token
    if not authorization or not secrets.compare_digest(authorization,f"Bearer {expected}"): raise HTTPException(401,detail={"code":"UNAUTHENTICATED","message":"Bot 服务令牌无效。"})
    if body_key is not None and body_key!="main": raise HTTPException(403,detail={"code":"FORBIDDEN","message":"bot_key 与服务令牌不匹配。"})


def reply(text: str,path: str|None=None,mode: str="same_context"):
    return {"command_id":str(__import__("uuid").uuid4()),"reply":{"mode":mode,"text":text,"links":[{"label":"打开 ShuttleUp","path":path}] if path else []},"resource":None}


def context_for(db,body): return db.scalar(select(BotContext).where(BotContext.bot_key==body.bot_key,BotContext.umo==body.umo))
def identity_for(db,body): return db.scalar(select(BotIdentity).where(BotIdentity.bot_key==body.bot_key,BotIdentity.platform_id==body.platform_id,BotIdentity.sender_id==body.sender_id))


@bot_router.post("/commands")
async def command(body: CommandRequest,authorization: str|None=Header(default=None),idempotency_key: str|None=Header(default=None),db: Session=Depends(get_db)):
    bot_auth(authorization,body.bot_key)
    if idempotency_key!=f"astrbot:{body.platform_id}:{body.message_id}": raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"Idempotency-Key 必须来自平台 message_id。"})
    from ..billing.routes import idempotent
    old,digest=idempotent(db,f"bot:{body.bot_key}:command",idempotency_key,body.model_dump())
    if old:return old.response
    identity=identity_for(db,body); context=context_for(db,body)
    if body.command=="help": result=reply("常用指令：创建、活动、当前、加入、课表、有空、没空、时间、推荐、场地、参加、到场、记账、账单、已付、收款、结算、结束、取消。")
    elif body.command=="identity.bind":
        raw=str(body.args.get("code", "")); token=db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash==token_hash(raw),OneTimeToken.purpose=="bot_bind",OneTimeToken.consumed_at.is_(None),OneTimeToken.expires_at>now_ms()))
        if not token: raise HTTPException(422,detail={"code":"INVALID_BIND_CODE","message":"绑定码无效或已过期。"})
        if context: raise HTTPException(422,detail={"code":"PRIVATE_REQUIRED","message":"账号绑定请在私聊中执行。"})
        identity=identity or BotIdentity(bot_key=body.bot_key,platform_id=body.platform_id,sender_id=body.sender_id,user_id=token.user_id,private_umo=body.umo); identity.user_id=token.user_id; identity.private_umo=body.umo; db.add(identity); token.consumed_at=now_ms(); result=reply("账号绑定成功。", "/me")
    elif not identity: result=reply("这个操作需要先绑定网页身份。请在个人设置生成绑定码，然后私聊发送“/羽球 绑定 绑定码”。","/me", "private")
    elif body.command=="context.bind":
        raw=str(body.args.get("code", "")); token=db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash==token_hash(raw),OneTimeToken.purpose=="group_bind",OneTimeToken.consumed_at.is_(None),OneTimeToken.expires_at>now_ms()))
        if not token: raise HTTPException(422,detail={"code":"INVALID_BIND_CODE","message":"群绑定码无效或已过期。"})
        activity=db.get(Activity,token.activity_id)
        if activity.host_user_id!=identity.user_id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有活动主持人可以关联群。"})
        context=context or BotContext(bot_key=body.bot_key,umo=body.umo,label=str(body.args.get("label","球友群"))); context.current_activity_id=activity.id; db.add(context); db.flush()
        if not db.scalar(select(BotActivityLink).where(BotActivityLink.context_id==context.id,BotActivityLink.activity_id==activity.id)): db.add(BotActivityLink(context_id=context.id,activity_id=activity.id))
        token.consumed_at=now_ms(); result=reply(f"已关联活动 {activity.short_code} · {activity.title}。",f"/a/{activity.id}")
    else:
        activity=None
        if body.activity_code: activity=db.scalar(select(Activity).where(Activity.short_code==body.activity_code.upper()))
        elif context and context.current_activity_id: activity=db.get(Activity,context.current_activity_id)
        user=db.get(User,identity.user_id)
        if body.command=="activity.create":
            from ..activities.routes import unique_code
            from ..security import invite_token,token as random_token,token_hash as digest_token
            from datetime import datetime,timedelta
            today=datetime.now().date(); aid=str(__import__("uuid").uuid4()); nonce=random_token(16); invite=invite_token(aid,nonce)
            activity=Activity(id=aid,short_code=unique_code(db),title=str(body.args.get("title","羽毛球约球"))[:80],host_user_id=user.id,date_from=(today+timedelta(days=1)).isoformat(),date_to=(today+timedelta(days=7)).isoformat(),daily_windows=[{"weekdays":[1,2,3,4,5,6,7],"start_time":"18:00","end_time":"22:00"}],invite_nonce=nonce,invite_token_hash=digest_token(invite),price_defaults={},venue_preferences=[]); db.add(activity); db.flush(); db.add(Participant(activity_id=activity.id,user_id=user.id,display_name=user.display_name,join_order=1,required=True)); emit(db,"activity.created",activity=activity,actor=user); result=reply(f"活动已创建：{activity.title}（{activity.short_code}）。",f"/a/{activity.id}")
        elif body.command=="activity.list":
            links=db.scalars(select(BotActivityLink).where(BotActivityLink.context_id==context.id)).all() if context else []
            activities=[db.get(Activity,link.activity_id) for link in links];result=reply("本群活动："+"；".join(f"{a.short_code} {a.title}（{a.status}）" for a in activities) if activities else "本群还没有关联活动。")
        elif body.command=="activity.current":
            if not activity: result=reply("本群还没有当前活动。")
            else: result=reply(f"{activity.short_code} · {activity.title} · {activity.status}，{activity.date_from} 至 {activity.date_to}。",f"/a/{activity.id}")
        elif body.command=="activity.switch":
            if not activity: result=reply("没有找到指定活动。")
            elif activity.host_user_id!=user.id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有该活动主持人可以切换当前活动。"})
            elif not context or not db.scalar(select(BotActivityLink).where(BotActivityLink.context_id==context.id,BotActivityLink.activity_id==activity.id)): raise HTTPException(403,detail={"code":"FORBIDDEN","message":"活动尚未关联到本群。"})
            else: context.current_activity_id=activity.id;result=reply(f"已切换到 {activity.short_code} · {activity.title}。",f"/a/{activity.id}")
        elif not activity: result=reply("请先关联或切换本群的当前活动。")
        elif body.command=="participant.join":
            if not context or not db.scalar(select(BotActivityLink).where(BotActivityLink.context_id==context.id,BotActivityLink.activity_id==activity.id)):raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只能加入本群已关联的活动。"})
            p=participant_for(db,activity.id,user.id,include_inactive=True)
            if p:p.membership="active"
            else:
                from sqlalchemy import func
                order=(db.scalar(select(func.max(Participant.join_order)).where(Participant.activity_id==activity.id)) or 0)+1;p=Participant(activity_id=activity.id,user_id=user.id,display_name=user.display_name,join_order=order);db.add(p)
            activity.version+=1;emit(db,"participant.joined",activity=activity,actor=user,payload={"participant_id":p.id});result=reply(f"已加入 {activity.title}。",f"/a/{activity.id}")
        elif not participant_for(db,activity.id,user.id): result=reply(f"你还未加入活动 {activity.short_code}。请先发送“/羽球 加入”。",f"/a/{activity.id}")
        elif body.command=="participant.leave":
            p=participant_for(db,activity.id,user.id)
            if activity.host_user_id==user.id:raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"主持人需先在网页转交主持人身份。"})
            p.membership="left";activity.version+=1;emit(db,"participant.left",activity=activity,actor=user,payload={"participant_id":p.id});result=reply(f"已退出 {activity.title}；与你有关的历史账款仍可查看。",f"/a/{activity.id}/bill")
        elif body.command=="schedule.open": result=reply("打开个人时间页导入 WakeUp 或编辑时间。","/me/time")
        elif body.command=="availability.set":
            day=str(body.args.get("date"));start_text,end_text=str(body.args.get("time","")).split("-",1);tz=ZoneInfo(activity.timezone);start=datetime.fromisoformat(f"{day}T{start_text}:00").replace(tzinfo=tz);end=datetime.fromisoformat(f"{day}T{end_text}:00").replace(tzinfo=tz)
            user.availability_revision+=1;personal=bool(body.args.get("personal"));rule=AvailabilityRule(user_id=user.id,activity_id=None if personal else activity.id,source="one_off" if personal else "activity",state=body.args.get("state"),kind="once",start_at=int(start.timestamp()*1000),end_at=int(end.timestamp()*1000),edit_seq=user.availability_revision);db.add(rule);activity.version+=1;emit(db,"availability.changed",activity=activity,actor=user,owner_user_id=user.id,payload={"revision":user.availability_revision});result=reply(f"已标记 {day} {start_text}–{end_text} 为{'空闲' if rule.state=='free' else '繁忙'}{'（同时写入个人时间）' if personal else '（仅本次）'}。",f"/a/{activity.id}")
        elif body.command=="rsvp.set":
            p=participant_for(db,activity.id,user.id)
            if not activity.current_plan_id or p.rsvp_plan_id!=activity.current_plan_id:raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"你不在当前拟参加名单中。"})
            p.rsvp=str(body.args.get("response"));activity.version+=1;emit(db,"rsvp.changed",activity=activity,actor=user,payload={"participant_id":p.id,"response":p.rsvp});result=reply("已记录："+("参加" if p.rsvp=="yes" else "不参加")+"。",f"/a/{activity.id}")
        elif body.command=="attendance.set":
            p=participant_for(db,activity.id,user.id);p.attendance=str(body.args.get("state"));activity.bill_generation+=1;activity.version+=1;emit(db,"attendance.changed",activity=activity,actor=user,payload={"participant_id":p.id,"state":p.attendance});result=reply("已标记"+("到场" if p.attendance=="present" else "缺席")+"，主持人出账前会核对。",f"/a/{activity.id}")
        elif body.command=="expense.create":
            p=participant_for(db,activity.id,user.id);raw_kind=str(body.args.get("kind"));value=str(body.args.get("value",""));description=str(body.args.get("description") or raw_kind)
            if raw_kind=="球":
                quantity=int(value.removesuffix("个"));unit=activity.price_defaults.get("shuttle_unit_cents")
                if unit is None:raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"本活动尚未设置球单价，请用“记账 球费 金额”。"})
                cents=quantity*unit;kind="shuttle"
            else:
                try:cents=int((Decimal(value)*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
                except (InvalidOperation,ValueError):raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"金额格式不正确。"})
                quantity=None;unit=None;kind="venue" if raw_kind=="场地" else "shuttle" if raw_kind=="球费" else "extra"
            expense=Expense(short_code=short_code(),activity_id=activity.id,kind=kind,description=description,amount_cents=cents,payer_participant_id=p.id,split_mode="equal",split_scope="attendees",quantity=quantity,unit_price_cents=unit,created_by=user.id);db.add(expense);activity.bill_generation+=1;activity.version+=1;emit(db,"expense.created",activity=activity,actor=user,payload={"expense_id":expense.id});result=reply(f"已记录{description} ¥{cents/100:.2f}，垫付人：你。费用编号 {expense.short_code}。",f"/a/{activity.id}/bill")
        elif body.command=="payment.confirm":
            p=participant_for(db,activity.id,user.id);claim=db.scalar(select(PaymentClaim).where(PaymentClaim.activity_id==activity.id,PaymentClaim.short_code==str(body.args.get("code")).upper()))
            if not claim or claim.to_participant_id!=p.id:raise HTTPException(403,detail={"code":"FORBIDDEN","message":"你不是这笔声明的收款人。"})
            if claim.status!="claimed":raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"该付款声明已处理。"})
            claim.status="confirmed";claim.confirmed_at=now_ms();claim.resolved_by_user_id=user.id;emit(db,"payment.confirmed",activity=activity,actor=user,payload={"payment_id":claim.id});result=reply(f"已确认收到 ¥{claim.amount_cents/100:.2f}。",f"/a/{activity.id}/bill")
        elif body.command=="payment.claim":
            p=participant_for(db,activity.id,user.id);bill=db.get(BillRevision,activity.current_bill_id) if activity.current_bill_id else None
            if not bill or activity.billing_status!="issued":raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"当前没有待支付账单。"})
            transfer=next((t for t in bill.snapshot["transfers"] if t["short_code"]==str(body.args.get("code")).upper()),None)
            if not transfer or transfer["from_participant_id"]!=p.id:raise HTTPException(403,detail={"code":"FORBIDDEN","message":"这不是你的付款任务。"})
            from sqlalchemy import func
            paid=db.scalar(select(func.coalesce(func.sum(PaymentClaim.amount_cents),0)).where(PaymentClaim.bill_revision_id==bill.id,PaymentClaim.transfer_id==transfer["id"],PaymentClaim.status=="confirmed")) or 0;remaining=transfer["amount_cents"]-paid
            if db.scalar(select(PaymentClaim.id).where(PaymentClaim.bill_revision_id==bill.id,PaymentClaim.transfer_id==transfer["id"],PaymentClaim.status=="claimed")):raise HTTPException(409,detail={"code":"PAYMENT_PENDING","message":"已有一笔付款等待确认。"})
            raw=body.args.get("amount");amount=remaining if raw is None else int((Decimal(str(raw))*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
            if amount<=0 or amount>remaining:raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"付款金额超过剩余金额。"})
            claim=PaymentClaim(short_code=short_code(),activity_id=activity.id,bill_revision_id=bill.id,transfer_id=transfer["id"],from_participant_id=p.id,to_participant_id=transfer["to_participant_id"],amount_cents=amount);db.add(claim);emit(db,"payment.claimed",activity=activity,actor=user,payload={"payment_id":claim.id});result=reply(f"已提交付款声明 ¥{amount/100:.2f}，编号 {claim.short_code}，等待收款人确认。",f"/a/{activity.id}/bill")
        elif body.command in ("availability.summary","candidate.list","venue.list","plan.open_select","booking.open_create","activity.open_finish","activity.open_cancel"): result=reply("已为你打开当前活动的对应操作。",f"/a/{activity.id}")
        elif body.command in ("expense.open_split","bill.show","bill.open_publish"): result=reply("已为你打开当前活动的账务操作。",f"/a/{activity.id}/bill", "private" if body.command=="bill.show" else "same_context")
        else: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"未知 Bot 指令。"})
    from ..models import OperationKey
    db.add(OperationKey(scope=f"bot:{body.bot_key}:command",key=idempotency_key,request_hash=digest,response_status=200,response=result,expires_at=now_ms()+30*86400000)); db.commit(); return result


@bot_router.get("/deliveries")
async def deliveries(wait: int=25,limit: int=20,authorization: str|None=Header(default=None)):
    bot_auth(authorization); deadline=time.monotonic()+min(max(wait,0),25)
    while True:
        with SessionLocal.begin() as db:
            rows=db.scalars(select(Notification).join(BotContext,Notification.target_context_id==BotContext.id).where(BotContext.bot_key=="main",Notification.state=="pending",Notification.available_at<=now_ms()).limit(min(limit,20))).all()
            if rows:
                result=[]
                for row in rows:
                    raw=secrets.token_urlsafe(24); row.state="leased"; row.lease_until=now_ms()+60000; row.lease_token_hash=token_hash(raw); row.attempts+=1; context=db.get(BotContext,row.target_context_id); result.append({"id":row.id,"lease_token":raw,"umo":context.umo,"event_type":row.payload.get("event_type"),"text":row.payload.get("text",""),"links":row.payload.get("links",[])})
                return {"items":result}
        if time.monotonic()>=deadline:return {"items":[]}
        await asyncio.sleep(.5)


def delivery_row(db,id,lease_token):
    row=db.get(Notification,id)
    if not row or row.state!="leased" or row.lease_until<now_ms() or not secrets.compare_digest(row.lease_token_hash or "",token_hash(lease_token)): raise HTTPException(409,detail={"code":"LEASE_INVALID","message":"通知租约无效或已过期。"})
    return row


@bot_router.post("/deliveries/{delivery_id}/ack")
async def ack(delivery_id: str,body: DeliveryResult,authorization: str|None=Header(default=None),db: Session=Depends(get_db)):
    bot_auth(authorization); row=delivery_row(db,delivery_id,body.lease_token); row.state="sent"; row.delivered_at=now_ms(); row.lease_token_hash=None; db.commit(); return {"status":"sent"}


@bot_router.post("/deliveries/{delivery_id}/fail")
async def fail(delivery_id: str,body: DeliveryResult,authorization: str|None=Header(default=None),db: Session=Depends(get_db)):
    bot_auth(authorization); row=delivery_row(db,delivery_id,body.lease_token); delays=[5,30,120,600]; row.state="failed" if row.attempts>=5 else "pending"; row.available_at=now_ms()+delays[min(row.attempts-1,3)]*1000; row.lease_token_hash=None; db.commit(); return {"status":row.state}
