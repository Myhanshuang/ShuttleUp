from datetime import datetime, timezone
import random
import string


def from_ms(value: int | None) -> str | None:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat() if value is not None else None


def to_ms(value: datetime | None) -> int | None:
    return int(value.timestamp() * 1000) if value is not None else None


def short_code(length: int = 4) -> str:
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))

