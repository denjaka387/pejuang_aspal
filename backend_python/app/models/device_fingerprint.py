from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DeviceFingerprint(Base):
    __tablename__ = "device_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), unique=True)

    # Permanent ownership binding
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)


    # integrity signals snapshot (MVP)
    is_rooted: Mapped[bool] = mapped_column(Boolean, default=False)
    app_tampered: Mapped[bool] = mapped_column(Boolean, default=False)
    mock_location_detected: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class SubscriptionTrial(Base):
    __tablename__ = "subscription_trials"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscription_trials_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    trial_started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    trial_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    # MVP: computed/persisted status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class AntiFraudWarning(Base):
    __tablename__ = "anti_fraud_warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    reason: Mapped[str] = mapped_column(String(255), default="")
    warning_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )

