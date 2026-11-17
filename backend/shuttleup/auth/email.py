"""Verified email registration. SMTP credentials and OTPs never enter responses/logs."""
import asyncio
import hashlib
import hmac
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import EmailChallenge, EmailIdentity, EmailSendAttempt, User, Participant, now_ms
from ..security import hash_password
from .service import current_user, require_csrf, create_session, public_user

router=APIRouter(tags=['identity'])


class EmailRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    @field_validator('email')
    @classmethod
    def normalize(cls,value):return str(value).lower()


class EmailRegister(EmailRequest):
    challenge_id: str = Field(min_length=32,max_length=36)
    code: str = Field(pattern=r'^\d{6}$')
    password: str = Field(min_length=10,max_length=200)
    display_name: str = Field(min_length=1,max_length=40)
    @field_validator('display_name')
    @classmethod
    def name(cls,value):
        if not value.strip():raise ValueError('empty name')
        return value.strip()


def fail(status,code,message):
    raise HTTPException(status,detail={'code':code,'message':message})


def digest(value):
    return hmac.new(get_settings().app_secret.encode(),value.encode(),hashlib.sha256).hexdigest()


def configured():
    settings=get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


def send_code(email,code):
    send_email(email, 'ShuttleUp 邮箱注册验证码', f'你的 ShuttleUp 注册验证码是：{code}\n\n10 分钟内有效，只能使用一次。若非本人操作，请忽略此邮件。')


def send_email(email, subject, content):
    settings=get_settings();message=EmailMessage()
    message['Subject']=subject
    message['From']=settings.smtp_from;message['To']=email
    message.set_content(content)
    context=ssl.create_default_context()
    if settings.smtp_security=='ssl':
        connection=smtplib.SMTP_SSL(settings.smtp_host,settings.smtp_port,timeout=15,context=context)
    else:
        connection=smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=15)
    with connection as smtp:
        if settings.smtp_security=='starttls':smtp.starttls(context=context)
        if settings.smtp_username:smtp.login(settings.smtp_username,settings.smtp_password or '')
        smtp.send_message(message)


def registration_user(request,db):
    user=current_user(request,db)
    if user:
        require_csrf(request)
        if user.username or user.email_account:fail(409,'ALREADY_REGISTERED','当前身份已有账号，请先退出登录。')
    return user


@router.get('/auth/options')
async def options():return {'email_registration':configured()}


@router.post('/auth/email/code',status_code=202)
async def issue(body:EmailRequest,request:Request,db:Session=Depends(get_db)):
    if not configured():fail(503,'EMAIL_NOT_CONFIGURED','管理员尚未配置邮件发送服务。')
    user=registration_user(request,db)
    if db.get(EmailIdentity,body.email):fail(409,'EMAIL_TAKEN','该邮箱已注册，请直接登录。')
    now=now_ms();ip=digest('ip:'+(request.client.host if request.client else 'unknown'));email_hash=digest('email:'+body.email)
    recent=db.scalar(select(EmailChallenge).where(EmailChallenge.email==body.email))
    if recent and now-recent.sent_at<60_000:fail(429,'CODE_COOLDOWN','请等待 60 秒后再发送。')
    for column,value,limit in [(EmailSendAttempt.email_hash,email_hash,5),(EmailSendAttempt.ip_hash,ip,20)]:
        count=db.scalar(select(func.count()).select_from(EmailSendAttempt).where(column==value,EmailSendAttempt.created_at>now-3600_000))
        if count>=limit:fail(429,'EMAIL_RATE_LIMITED','发送次数过多，请稍后再试。')
    db.execute(delete(EmailSendAttempt).where(EmailSendAttempt.created_at<now-86400_000))
    db.execute(delete(EmailChallenge).where(EmailChallenge.email==body.email))
    code=f'{secrets.randbelow(1_000_000):06d}';cid=str(uuid4())
    row=EmailChallenge(id=cid,email=body.email,owner_user_id=user.id if user else None,
                       code_hash=digest(cid+':'+code),sent_at=now,expires_at=now+600_000)
    db.add(row);db.add(EmailSendAttempt(email_hash=email_hash,ip_hash=ip,created_at=now))
    try:db.commit()
    except IntegrityError:
        db.rollback();fail(429,'CODE_COOLDOWN','验证码正在发送，请稍后再试。')
    try:await asyncio.to_thread(send_code,body.email,code)
    except Exception:
        db.execute(delete(EmailChallenge).where(EmailChallenge.id==cid));db.commit()
        fail(503,'EMAIL_SEND_FAILED','邮件发送失败，请稍后重试或联系管理员。')
    db.execute(update(EmailChallenge).where(EmailChallenge.id==cid).values(delivered=True));db.commit()
    return {'challenge_id':cid,'expires_in':600,'retry_after':60}


@router.post('/auth/email/register',status_code=201)
async def register(body:EmailRegister,request:Request,response:Response,db:Session=Depends(get_db)):
    user=registration_user(request,db)
    row=db.get(EmailChallenge,body.challenge_id);now=now_ms()
    if (not row or row.email!=body.email or row.owner_user_id!=(user.id if user else None)
            or not row.delivered or row.used_at or row.expires_at<=now or row.attempts>=5):
        fail(422,'INVALID_EMAIL_CODE','验证码无效或已过期，请重新获取。')
    if not hmac.compare_digest(row.code_hash,digest(row.id+':'+body.code)):
        db.execute(update(EmailChallenge).where(EmailChallenge.id==row.id).values(attempts=EmailChallenge.attempts+1));db.commit()
        fail(422,'INVALID_EMAIL_CODE','验证码不正确。')
    # Conditional consumption and identity creation commit together, preventing replay.
    consumed=db.execute(update(EmailChallenge).where(EmailChallenge.id==row.id,
        EmailChallenge.used_at.is_(None),EmailChallenge.expires_at>now,EmailChallenge.attempts<5).values(used_at=now))
    if consumed.rowcount!=1:db.rollback();fail(422,'INVALID_EMAIL_CODE','验证码已使用，请重新获取。')
    user=user or User(display_name=body.display_name)
    user.display_name=body.display_name;user.password_hash=hash_password(body.password)
    designated = get_settings().bootstrap_admin_email
    if designated and body.email == str(designated).lower():
        user.is_admin = True
    db.add(user)
    try:
        db.flush();db.add(EmailIdentity(email=body.email,user_id=user.id,verified_at=now));db.flush()
        for participant in db.scalars(select(Participant).where(Participant.user_id==user.id)):
            participant.display_name=user.display_name
        csrf=create_session(db,response,user)
        db.commit();db.refresh(user)
    except IntegrityError:
        db.rollback();fail(409,'EMAIL_TAKEN','该邮箱已注册，请直接登录。')
    return {'user':public_user(user),'csrf_token':csrf}
