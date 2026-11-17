from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Participant, User, WebSession, EmailIdentity
from ..security import hash_password, token_hash, verify_password, session_expiry
from ..config import get_settings
from .recovery import issue_recovery
from .schemas import GuestCreate, LoginRequest, PasswordUpdate, ProfileUpdate
from .service import COOKIE, create_session, csrf_for, current_user, public_user, require_csrf, require_user

router = APIRouter(tags=["identity"])


@router.get("/session")
async def session(request: Request, response: Response, db: Session = Depends(get_db)):
    user = current_user(request, db)
    raw = request.cookies.get(COOKIE)
    response.headers["Cache-Control"] = "no-store"
    if user and not user.username and not user.email_account and raw:
        row = db.scalar(select(WebSession).where(WebSession.token_hash == token_hash(raw)))
        expiry = session_expiry()
        if row and row.expires_at < expiry - 24 * 3600 * 1000:
            row.expires_at = expiry
            db.commit()
            response.set_cookie(COOKIE, raw, httponly=True, secure=get_settings().session_cookie_secure,
                                samesite="lax", max_age=30 * 24 * 3600, path="/")
    return {"user": public_user(user) if user else None, "csrf_token": csrf_for(raw) if user and raw else None}


@router.post("/auth/guest", status_code=201)
async def guest(body: GuestCreate, response: Response, db: Session = Depends(get_db)):
    user = User(display_name=body.display_name.strip())
    db.add(user); db.flush()
    csrf = create_session(db, response, user)
    recovery_code = issue_recovery(db, user)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"user": public_user(user), "csrf_token": csrf, "recovery_code": recovery_code}


@router.post("/auth/register", deprecated=True)
async def register():
    raise HTTPException(403, detail={"code": "REGISTRATION_DISABLED", "message": "用户名注册已关闭，请使用邮箱验证码注册。"})


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    identifier=body.username.strip().lower()
    if "@" in identifier:
        identity=db.get(EmailIdentity,identifier)
        user=db.get(User,identity.user_id) if identity else None
    else:
        user = db.scalar(select(User).where(User.username == identifier))
    if not user or not user.password_hash or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "账号或密码不正确。"})
    csrf = create_session(db, response, user)
    db.commit()
    return {"user": public_user(user), "csrf_token": csrf}


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    require_csrf(request)
    raw = request.cookies.get(COOKIE)
    if raw:
        db.execute(delete(WebSession).where(WebSession.token_hash == token_hash(raw)))
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
async def me(request: Request, db: Session = Depends(get_db)):
    return public_user(require_user(request, db))


@router.patch("/me")
async def update_me(body: ProfileUpdate,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request)
    if user.version!=body.expected_version:raise HTTPException(409,detail={"code":"VERSION_CONFLICT","message":"个人资料刚刚有更新。","current_version":user.version})
    user.display_name=body.display_name.strip();user.timezone=body.timezone;user.version+=1
    for participant in db.scalars(select(Participant).where(Participant.user_id==user.id)).all():participant.display_name=user.display_name
    db.commit();return public_user(user)


@router.put("/me/password",status_code=204)
async def update_password(body: PasswordUpdate,request: Request,db: Session=Depends(get_db)):
    user=require_user(request,db);require_csrf(request)
    if user.password_hash and (not body.current_password or not verify_password(user.password_hash,body.current_password)):raise HTTPException(403,detail={"code":"FORBIDDEN","message":"当前密码不正确。"})
    user.password_hash=hash_password(body.new_password);raw=request.cookies.get(COOKIE);current_hash=token_hash(raw) if raw else "";db.execute(delete(WebSession).where(WebSession.user_id==user.id,WebSession.token_hash!=current_hash));db.commit()
