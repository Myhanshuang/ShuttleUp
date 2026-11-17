import asyncio
import secrets
import time
from decimal import InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..activities.service import require_host
from ..auth.service import require_csrf, require_user
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import Activity, BotContext, Notification, OneTimeToken, User, now_ms
from ..security import token_hash

web_router=APIRouter(tags=["bot-bindings"])
bot_router=APIRouter(tags=["bot"])


class CommandRequest(BaseModel):
    bot_key: str
    platform_id: str
    sender_id: str = Field(min_length=1, max_length=120)
    sender_name: str = Field(default="球友", max_length=40)
    is_private: bool = False
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


@bot_router.post("/commands")
async def command(body: CommandRequest, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    bot_auth(authorization, body.bot_key)
    if idempotency_key != f"astrbot:{body.platform_id}:{body.message_id}":
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Idempotency-Key 必须来自平台 message_id。"})
    from ..billing.routes import idempotent
    from ..models import OperationKey
    from .helper import dispatch, AtomicSession
    from pydantic import ValidationError
    old, digest = idempotent(db, f"bot:{body.bot_key}:command", idempotency_key, body.model_dump())
    if old:
        return old.response
    try:
        result = await dispatch(body, AtomicSession(db), idempotency_key)
    except (ValidationError, ValueError, InvalidOperation) as error:
        db.rollback()
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "请检查指令参数、日期、时段或金额。"}) from error
    db.add(OperationKey(scope=f"bot:{body.bot_key}:command", key=idempotency_key, request_hash=digest, response_status=200, response=result, expires_at=now_ms()+30*86400000))
    db.commit()
    return result


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


class BotLoginRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


@web_router.post("/auth/bot-login")
async def bot_login(body: BotLoginRequest, response: Response, db: Session = Depends(get_db)):
    from sqlalchemy import update
    from ..auth.service import create_session, public_user
    row = db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == token_hash(body.token), OneTimeToken.purpose == "bot_login", OneTimeToken.consumed_at.is_(None), OneTimeToken.expires_at > now_ms()))
    if not row:
        raise HTTPException(422, detail={"code": "INVALID_LOGIN_TOKEN", "message": "登录链接无效或已过期，请私聊 Bot 重新获取。"})
    changed = db.execute(update(OneTimeToken).where(OneTimeToken.id == row.id, OneTimeToken.consumed_at.is_(None)).values(consumed_at=now_ms()))
    if changed.rowcount != 1:
        raise HTTPException(409, detail={"code": "TOKEN_USED", "message": "登录链接已经使用。"})
    user = db.get(User, row.user_id)
    csrf = create_session(db, response, user)
    db.commit()
    return {"user": public_user(user), "csrf_token": csrf}
