from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="driver")

    full_name: Mapped[str] = mapped_column(String(120), default="")
    whatsapp_number: Mapped[str] = mapped_column(String(32), default="")
    vehicle_type: Mapped[str] = mapped_column(String(16), default="motor")  # motor/mobil

    # MVP: App ecosystem (ride-hailing/logistics apps) used by driver.
    # Stored as CSV string like: "gojek,grab,maxim,indrive,lalamove".
    app_ecosystem: Mapped[str] = mapped_column(String(512), default="")

    premium_until: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_until: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    banned_reason: Mapped[str] = mapped_column(String(255), nullable=True)

    # Fake GPS / anti-fraud flags (MVP stub)
    mock_location_detected: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.timezone.utc),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )

