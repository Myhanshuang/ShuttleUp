"""Purpose-bound, single-use email recovery; reset revokes every web session."""
import asyncio
import hmac
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import EmailIdentity, EmailSendAttempt, PasswordResetChallenge, User, WebSession, now_ms
from ..security import hash_password
from .email import EmailRequest, configured, digest, fail, send_email
from .service import COOKIE, current_user, require_csrf

router = APIRouter(tags=["identity"])


class ResetPassword(EmailRequest):
    challenge_id: str = Field(min_length=32, max_length=36)
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=10, max_length=200)


def send_reset_code(address, code):
    send_email(address, "ShuttleUp 密码找回验证码",
        f"你的 ShuttleUp 密码找回验证码是：{code}\n\n10 分钟内有效。重设密码后，所有设备需要重新登录。若非本人操作，请忽略此邮件，不要向他人提供验证码。")


@router.post("/auth/password/code", status_code=202)
async def issue(body: EmailRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if current_user(request, db): require_csrf(request)
    if not configured(): fail(503, "EMAIL_NOT_CONFIGURED", "管理员尚未配置邮件发送服务。")
    now = now_ms()
    recent = db.scalar(select(PasswordResetChallenge).where(PasswordResetChallenge.email == body.email))
    if recent and now - recent.sent_at < 60_000:
        fail(429, "CODE_COOLDOWN", "请等待 60 秒后再发送。")
    email_hash = digest("email:" + body.email)
    ip_hash = digest("ip:" + (request.client.host if request.client else "unknown"))
    for column, value, limit in [(EmailSendAttempt.email_hash, email_hash, 5), (EmailSendAttempt.ip_hash, ip_hash, 20)]:
        count = db.scalar(select(func.count()).select_from(EmailSendAttempt).where(column == value, EmailSendAttempt.created_at > now - 3_600_000))
        if count >= limit: fail(429, "EMAIL_RATE_LIMITED", "发送次数过多，请稍后再试。")
    identity = db.get(EmailIdentity, body.email)
    user = db.get(User, identity.user_id) if identity else None
    eligible = bool(user and not user.disabled_at)
    cid, code = str(uuid4()), f"{secrets.randbelow(1_000_000):06d}"
    db.execute(delete(EmailSendAttempt).where(EmailSendAttempt.created_at < now - 86_400_000))
    db.execute(delete(PasswordResetChallenge).where(PasswordResetChallenge.email == body.email))
    db.add(PasswordResetChallenge(id=cid, email=body.email, user_id=user.id if eligible else None,
        code_hash=digest("reset:" + cid + ":" + code), sent_at=now, expires_at=now + 600_000))
    db.add(EmailSendAttempt(email_hash=email_hash, ip_hash=ip_hash, created_at=now))
    try: db.commit()
    except IntegrityError:
        db.rollback(); fail(429, "CODE_COOLDOWN", "验证码正在发送，请稍后再试。")
    if eligible:
        try: await asyncio.to_thread(send_reset_code, body.email, code)
        except Exception:
            db.execute(delete(PasswordResetChallenge).where(PasswordResetChallenge.id == cid)); db.commit()
            fail(503, "EMAIL_SEND_FAILED", "邮件发送失败，请稍后重试或联系管理员。")
    db.execute(update(PasswordResetChallenge).where(PasswordResetChallenge.id == cid).values(delivered=True)); db.commit()
    # Same response and cooldown for unregistered/disabled email addresses.
    return {"challenge_id": cid, "expires_in": 600, "retry_after": 60,
        "message": "如果该邮箱已注册，验证码将发送到邮箱；10 分钟内有效。"}


@router.post("/auth/password/reset")
async def reset(body: ResetPassword, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if current_user(request, db): require_csrf(request)
    row = db.get(PasswordResetChallenge, body.challenge_id)
    now = now_ms()
    if not row or row.email != body.email or not row.delivered or row.used_at or row.expires_at <= now or row.attempts >= 5:
        fail(422, "INVALID_EMAIL_CODE", "验证码无效或已过期，请重新获取。")
    if not hmac.compare_digest(row.code_hash, digest("reset:" + row.id + ":" + body.code)):
        db.execute(update(PasswordResetChallenge).where(PasswordResetChallenge.id == row.id).values(attempts=PasswordResetChallenge.attempts + 1)); db.commit()
        fail(422, "INVALID_EMAIL_CODE", "验证码不正确。")
    identity = db.get(EmailIdentity, row.email)
    user = db.get(User, row.user_id) if row.user_id else None
    if not user or user.disabled_at or not identity or identity.user_id != user.id:
        fail(422, "INVALID_EMAIL_CODE", "验证码无效或已过期，请重新获取。")
    password_hash = hash_password(body.password)
    consumed = db.execute(update(PasswordResetChallenge).where(PasswordResetChallenge.id == row.id,
        PasswordResetChallenge.used_at.is_(None), PasswordResetChallenge.expires_at > now,
        PasswordResetChallenge.attempts < 5).values(used_at=now))
    if consumed.rowcount != 1:
        db.rollback(); fail(422, "INVALID_EMAIL_CODE", "验证码已使用，请重新获取。")
    user.password_hash = password_hash
    user.version += 1
    db.execute(delete(WebSession).where(WebSession.user_id == user.id))
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"message": "密码已重设，请使用新密码登录。所有设备的旧登录均已失效。"}
