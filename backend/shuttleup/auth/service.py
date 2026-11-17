from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User, WebSession
from ..security import csrf_for, session_expiry, token, token_hash

COOKIE = "shuttleup_session"


def public_user(user: User) -> dict:
    return {"id": user.id, "display_name": user.display_name, "username": user.username, "email": user.email_account.email if user.email_account else None, "is_admin": user.is_admin, "timezone": user.timezone, "version": user.version}


def create_session(db: Session, response: Response, user: User) -> str:
    raw = token()
    db.add(WebSession(token_hash=token_hash(raw), user_id=user.id, expires_at=session_expiry()))
    response.set_cookie(COOKIE, raw, httponly=True, secure=get_settings().session_cookie_secure, samesite="lax", max_age=30 * 24 * 3600, path="/")
    return csrf_for(raw)


class HelperRequest(Request):
    """Internal principal after trusted Bot transport authentication; never built from HTTP fields."""
    def __init__(self, user_id: str):
        super().__init__({"type": "http", "headers": [], "method": "POST", "path": "/"})
        self.helper_user_id = user_id


def current_user(request: Request, db: Session) -> User | None:
    if isinstance(request, HelperRequest):
        return db.get(User, request.helper_user_id)
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    session = db.scalar(select(WebSession).where(WebSession.token_hash == token_hash(raw), WebSession.expires_at > __import__("time").time() * 1000))
    return db.get(User, session.user_id) if session else None


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(401, detail={"code": "UNAUTHENTICATED", "message": "请先登录。"})
    return user


def require_csrf(request: Request) -> None:
    if isinstance(request, HelperRequest):
        return  # Bot transport has already authenticated; no browser cookies are used.
    raw = request.cookies.get(COOKIE)
    if not raw or not hmac_compare(request.headers.get("x-csrf-token", ""), csrf_for(raw)):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "请求校验失败，请刷新页面后重试。"})


def hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)

