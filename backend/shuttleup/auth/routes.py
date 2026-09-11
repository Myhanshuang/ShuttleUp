from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Participant, User, WebSession
from ..security import hash_password, token_hash, verify_password
from .schemas import GuestCreate, LoginRequest, PasswordUpdate, ProfileUpdate, RegisterRequest
from .service import COOKIE, create_session, csrf_for, current_user, public_user, require_csrf, require_user

router = APIRouter(tags=["identity"])


@router.get("/session")
async def session(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    raw = request.cookies.get(COOKIE)
    return {"user": public_user(user) if user else None, "csrf_token": csrf_for(raw) if user and raw else None}


@router.post("/auth/guest", status_code=201)
async def guest(body: GuestCreate, response: Response, db: Session = Depends(get_db)):
    user = User(display_name=body.display_name.strip())
    db.add(user); db.flush()
    csrf = create_session(db, response, user)
    db.commit()
    return {"user": public_user(user), "csrf_token": csrf}


@router.post("/auth/register", status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user and user.username:
        raise HTTPException(409, detail={"code": "ALREADY_REGISTERED", "message": "当前身份已有账号。"})
    user = user or User(display_name=body.display_name or body.username)
    user.username = body.username
    user.password_hash = hash_password(body.password)
    if body.display_name:
        user.display_name = body.display_name.strip()
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, detail={"code": "USERNAME_TAKEN", "message": "用户名已被使用。"})
    csrf = create_session(db, response, user) if not request.cookies.get(COOKIE) else csrf_for(request.cookies[COOKIE])
    db.commit()
    return {"user": public_user(user), "csrf_token": csrf}


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    if not user or not user.password_hash or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "用户名或密码不正确。"})
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
