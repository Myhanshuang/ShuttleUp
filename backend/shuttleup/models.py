from __future__ import annotations

import time
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now_ms() -> int:
    return int(time.time() * 1000)


class Versioned:
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    updated_at: Mapped[int] = mapped_column(Integer, default=now_ms, onupdate=now_ms)
    version: Mapped[int] = mapped_column(Integer, default=1)


class User(Base, Versioned):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    display_name: Mapped[str] = mapped_column(String(40))
    username: Mapped[str | None] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_account: Mapped[EmailIdentity | None] = relationship(uselist=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    availability_revision: Mapped[int] = mapped_column(Integer, default=0)
    disabled_at: Mapped[int | None] = mapped_column(Integer)


class WebSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class AppSetting(Base, Versioned):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    court_hourly_cents: Mapped[int | None] = mapped_column(Integer)
    shuttle_unit_cents: Mapped[int | None] = mapped_column(Integer)
    shuttle_label: Mapped[str | None] = mapped_column(String(80))
    guest_join_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Activity(Base, Versioned):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    short_code: Mapped[str] = mapped_column(String(8), unique=True)
    title: Mapped[str] = mapped_column(String(80))
    host_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="collecting")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    date_from: Mapped[str] = mapped_column(String(10))
    date_to: Mapped[str] = mapped_column(String(10))
    daily_windows: Mapped[list] = mapped_column(JSON)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)
    min_players: Mapped[int] = mapped_column(Integer, default=4)
    max_players: Mapped[int] = mapped_column(Integer, default=6)
    court_count: Mapped[int] = mapped_column(Integer, default=1)
    venue_preferences: Mapped[list] = mapped_column(JSON, default=list)
    decision_deadline: Mapped[int | None] = mapped_column(Integer)
    invite_nonce: Mapped[str] = mapped_column(String(64))
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    invite_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    price_defaults: Mapped[dict] = mapped_column(JSON, default=dict)
    current_plan_id: Mapped[str | None] = mapped_column(String(36))
    billing_status: Mapped[str] = mapped_column(String(16), default="draft")
    bill_generation: Mapped[int] = mapped_column(Integer, default=0)
    current_bill_id: Mapped[str | None] = mapped_column(String(36))
    archived_at: Mapped[int | None] = mapped_column(Integer)
    cancel_reason: Mapped[str | None] = mapped_column(String(240))


class Participant(Base, Versioned):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("activity_id", "user_id"),
        UniqueConstraint("activity_id", "join_order"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    display_name: Mapped[str] = mapped_column(String(40))
    join_order: Mapped[int] = mapped_column(Integer)
    membership: Mapped[str] = mapped_column(String(12), default="active")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    rsvp: Mapped[str] = mapped_column(String(12), default="pending")
    rsvp_plan_id: Mapped[str | None] = mapped_column(String(36))
    attendance: Mapped[str] = mapped_column(String(12), default="unknown")
    attendance_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"), index=True)
    import_id: Mapped[str | None] = mapped_column(String(36), index=True)
    origin_plan_id: Mapped[str | None] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(12))
    start_at: Mapped[int | None] = mapped_column(Integer)
    end_at: Mapped[int | None] = mapped_column(Integer)
    recurrence: Mapped[dict | None] = mapped_column(JSON)
    edit_seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class ScheduleImport(Base):
    __tablename__ = "schedule_imports"
    __table_args__ = (UniqueConstraint("user_id", "provider_key", "label"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(80))
    term_start_date: Mapped[str] = mapped_column(String(10))
    term_end_date: Mapped[str] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    occurrence_count: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class ProviderConfig(Base, Versioned):
    __tablename__ = "provider_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    adapter_key: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_env: Mapped[str | None] = mapped_column(String(100))
    min_poll_seconds: Mapped[int] = mapped_column(Integer, default=30)
    min_request_interval_seconds: Mapped[int] = mapped_column(Integer, default=2)
    fresh_for_seconds: Mapped[int] = mapped_column(Integer, default=90)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Venue(Base, Versioned):
    __tablename__ = "venues"
    __table_args__ = (UniqueConstraint("provider_id", "external_venue_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id"), index=True)
    external_venue_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(240), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    booking_url: Mapped[str] = mapped_column(Text, default="")
    hourly_rate_cents: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class VenueSnapshot(Base):
    __tablename__ = "venue_snapshots"
    __table_args__ = (UniqueConstraint("venue_id", "local_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id"), index=True)
    local_date: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64))
    slots: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    last_success_at: Mapped[int | None] = mapped_column(Integer)
    last_attempt_at: Mapped[int] = mapped_column(Integer)
    next_poll_at: Mapped[int] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    reported_stale_at: Mapped[int | None] = mapped_column(Integer)


class ActivityPlan(Base):
    __tablename__ = "activity_plans"
    __table_args__ = (UniqueConstraint("activity_id", "plan_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    plan_no: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[int] = mapped_column(Integer)
    ends_at: Mapped[int] = mapped_column(Integer)
    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id"))
    court_ids: Mapped[list] = mapped_column(JSON)
    roster_participant_ids: Mapped[list] = mapped_column(JSON)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    selected_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class Booking(Base, Versioned):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("activity_plans.id"), index=True)
    venue_id: Mapped[str] = mapped_column(ForeignKey("venues.id"))
    court_ids: Mapped[list] = mapped_column(JSON)
    starts_at: Mapped[int] = mapped_column(Integer)
    ends_at: Mapped[int] = mapped_column(Integer)
    external_order_no: Mapped[str | None] = mapped_column(String(120))
    booker_participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    quoted_total_cents: Mapped[int | None] = mapped_column(Integer)
    paid_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    payer_participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    note: Mapped[str | None] = mapped_column(String(240))


class Expense(Base, Versioned):
    __tablename__ = "expenses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    short_code: Mapped[str] = mapped_column(String(8), unique=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(120))
    amount_cents: Mapped[int] = mapped_column(Integer)
    payer_participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    split_mode: Mapped[str] = mapped_column(String(12))
    split_scope: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer)
    booking_id: Mapped[str | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    refund_of_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[int | None] = mapped_column(Integer)


class ExpenseShare(Base):
    __tablename__ = "expense_shares"
    __table_args__ = (UniqueConstraint("expense_id", "participant_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    expense_id: Mapped[str] = mapped_column(ForeignKey("expenses.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    exact_amount_cents: Mapped[int | None] = mapped_column(Integer)


class BillRevision(Base):
    __tablename__ = "bill_revisions"
    __table_args__ = (UniqueConstraint("activity_id", "revision_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    source_generation: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    total_cents: Mapped[int] = mapped_column(Integer)
    published_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[int] = mapped_column(Integer, default=now_ms)


class PaymentClaim(Base):
    __tablename__ = "payment_claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    short_code: Mapped[str] = mapped_column(String(8), unique=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), index=True)
    bill_revision_id: Mapped[str] = mapped_column(ForeignKey("bill_revisions.id"), index=True)
    transfer_id: Mapped[str] = mapped_column(String(36))
    from_participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    to_participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="claimed")
    claimed_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    confirmed_at: Mapped[int | None] = mapped_column(Integer)
    resolved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


Index("uq_pending_payment", PaymentClaim.bill_revision_id, PaymentClaim.transfer_id, unique=True, sqlite_where=PaymentClaim.status == "claimed")


class OneTimeToken(Base):
    __tablename__ = "one_time_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"))
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    expires_at: Mapped[int] = mapped_column(Integer)
    consumed_at: Mapped[int | None] = mapped_column(Integer)


class BotIdentity(Base):
    __tablename__ = "bot_identities"
    __table_args__ = (UniqueConstraint("bot_key", "platform_id", "sender_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    bot_key: Mapped[str] = mapped_column(String(40))
    platform_id: Mapped[str] = mapped_column(String(40))
    sender_id: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    private_umo: Mapped[str | None] = mapped_column(Text)


class BotContext(Base):
    __tablename__ = "bot_contexts"
    __table_args__ = (UniqueConstraint("bot_key", "umo"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    bot_key: Mapped[str] = mapped_column(String(40))
    umo: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(120), default="")
    current_activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"))


class BotActivityLink(Base):
    __tablename__ = "bot_activity_links"
    __table_args__ = (UniqueConstraint("context_id", "activity_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    context_id: Mapped[str] = mapped_column(ForeignKey("bot_contexts.id"))
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"))
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_seq: Mapped[int | None] = mapped_column(ForeignKey("events.seq"))
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    target_context_id: Mapped[str | None] = mapped_column(ForeignKey("bot_contexts.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    available_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    lease_until: Mapped[int | None] = mapped_column(Integer)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[int | None] = mapped_column(Integer)
    read_at: Mapped[int | None] = mapped_column(Integer)


class Event(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    type: Mapped[str] = mapped_column(String(40))
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"), index=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    resource_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[int] = mapped_column(Integer, default=now_ms)
    processed_at: Mapped[int | None] = mapped_column(Integer)


class OperationKey(Base):
    __tablename__ = "operation_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scope: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[int] = mapped_column(Integer)


Index("ix_activities_host_status", Activity.host_user_id, Activity.status)


class EmailIdentity(Base):
    __tablename__ = "email_identities"
    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    verified_at: Mapped[int] = mapped_column(Integer)


class EmailChallenge(Base):
    __tablename__ = "email_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[int | None] = mapped_column(Integer)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailSendAttempt(Base):
    __tablename__ = "email_send_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[int] = mapped_column(Integer, index=True)


class GuestRecovery(Base):
    __tablename__ = "guest_recovery"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)


class PasswordResetChallenge(Base):
    __tablename__ = "password_reset_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[int | None] = mapped_column(Integer)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
