import base64
import hashlib
import hmac
import secrets
import time

from argon2 import PasswordHasher

from .config import get_settings

password_hasher = PasswordHasher()


def token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_password(raw: str) -> str:
    return password_hasher.hash(raw)


def verify_password(encoded: str, raw: str) -> bool:
    try:
        return password_hasher.verify(encoded, raw)
    except Exception:
        return False


def csrf_for(raw_session: str) -> str:
    digest = hmac.new(get_settings().app_secret.encode(), f"csrf:{raw_session}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def invite_token(activity_id: str, nonce: str) -> str:
    digest = hmac.new(get_settings().app_secret.encode(), f"invite:{activity_id}:{nonce}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def session_expiry() -> int:
    return int(time.time() * 1000) + 30 * 24 * 60 * 60 * 1000
