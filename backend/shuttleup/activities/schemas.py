from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


def tomorrow() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)


class DailyWindow(BaseModel):
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1)
    start_time: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    timezone: str = "Asia/Shanghai"
    date_from: date = Field(default_factory=tomorrow)
    date_to: date | None = None
    daily_windows: list[DailyWindow] = Field(default_factory=lambda: [DailyWindow()])
    duration_minutes: int = Field(default=120, ge=30, le=360, multiple_of=15)
    min_players: int = Field(default=4, ge=2, le=30)
    max_players: int = Field(default=6, ge=2, le=30)
    court_count: int = Field(default=1, ge=1, le=8)
    venue_preferences: list[str] = Field(default_factory=list)
    decision_deadline: datetime | None = None
    price_overrides: dict[str, int | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self):
        self.date_to = self.date_to or self.date_from + timedelta(days=6)
        if self.date_to < self.date_from or (self.date_to - self.date_from).days > 13:
            raise ValueError("日期范围最多 14 天")
        if self.min_players > self.max_players:
            raise ValueError("最少人数不能超过最多人数")
        for window in self.daily_windows:
            if window.end_time <= window.start_time:
                raise ValueError("允许时段必须在同一天内结束")
        return self


class JoinAvailability(BaseModel):
    date: date
    start: str = Field(pattern=r"^(?:[01]\d|2[01]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-2]):[0-5]\d$")

    @model_validator(mode="after")
    def valid_interval(self):
        if not "08:00" <= self.start < self.end <= "22:00":
            raise ValueError("空闲时间须在 08:00–22:00 内，结束时间晚于开始时间")
        return self


class JoinRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    availability: list[JoinAvailability] = Field(default_factory=list, max_length=28)


class ActivityPatch(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=30, le=360, multiple_of=15)
    date_from: date | None = None
    date_to: date | None = None
    daily_windows: list[DailyWindow] | None = Field(default=None, min_length=1, max_length=14)
    venue_preferences: list[str] | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, min_length=1, max_length=80)
    decision_deadline: datetime | None = None
    expected_version: int


class CloneRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    date_from: date
    date_to: date


class InviteAction(BaseModel):
    action: str = Field(pattern="^(rotate|disable)$")
    expected_version: int


class HostTransfer(BaseModel):
    new_host_user_id: str
    expected_version: int


class ParticipantPatch(BaseModel):
    required: bool | None = None
    membership: str | None = Field(default=None, pattern="^(active|removed)$")
    expected_version: int


class OfflineParticipant(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)
