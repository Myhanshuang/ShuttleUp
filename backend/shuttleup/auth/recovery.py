"""High-entropy, single-use guest credentials; only hashes are persisted."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import GuestRecovery, User, WebSession
from ..security import token, token_hash
from .service import create_session, current_user, public_user, require_csrf, require_user

router = APIRouter(tags=['identity'])


def issue_recovery(db: Session, user: User) -> str:
    raw = token(24)
    row = db.get(GuestRecovery, user.id)
    if row:
        row.code_hash = token_hash(raw)
    else:
        db.add(GuestRecovery(user_id=user.id, code_hash=token_hash(raw)))
    return raw


def require_guest(user: User):
    if user.username or user.email_account or user.disabled_at:
        raise HTTPException(403, detail={'code': 'NOT_GUEST', 'message': '该身份已绑定账号，请使用账号登录。'})


@router.post('/me/guest-recovery')
async def issue(request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_user(request, db)
    require_csrf(request)
    require_guest(user)
    raw = issue_recovery(db, user)
    db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'recovery_code': raw}


class RecoverRequest(BaseModel):
    recovery_code: str = Field(min_length=32, max_length=128)


@router.post('/auth/guest/recover')
async def recover(body: RecoverRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if current_user(request, db):
        raise HTTPException(409, detail={'code': 'ALREADY_LOGGED_IN', 'message': '请先退出当前身份，再恢复其他游客身份。'})
    old_hash = token_hash(body.recovery_code.strip())
    row = db.scalar(select(GuestRecovery).where(GuestRecovery.code_hash == old_hash))
    user = db.get(User, row.user_id) if row else None
    if not user or user.disabled_at or user.username or user.email_account:
        raise HTTPException(422, detail={'code': 'INVALID_RECOVERY_CODE', 'message': '恢复码无效或已使用；已绑定邮箱的身份请用邮箱登录。'})
    raw = token(24)
    result = db.execute(update(GuestRecovery).where(GuestRecovery.user_id == user.id,
        GuestRecovery.code_hash == old_hash).values(code_hash=token_hash(raw)))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(422, detail={'code': 'INVALID_RECOVERY_CODE', 'message': '恢复码已使用，请使用最新恢复码。'})
    db.execute(delete(WebSession).where(WebSession.user_id == user.id))
    csrf = create_session(db, response, user)
    db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'user': public_user(user), 'csrf_token': csrf, 'recovery_code': raw}
