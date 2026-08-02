from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from .base import Base



class OrderStatus(str, Enum):
    created = "created"
    bidding = "bidding"
    ongoing = "ongoing"  # alias/legacy

    # Tracking stages (spec: berjenjang)
    to_pickup = "to_pickup"
    arrived_pickup = "arrived_pickup"
    on_trip = "on_trip"
    arrived_destination = "arrived_destination"
    back_to_start = "back_to_start"

    completed = "completed"
    cancelled = "cancelled"



class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    passenger_name: Mapped[str] = mapped_column(String(120), default="")
    passenger_contact: Mapped[str] = mapped_column(String(32), default="")

    vehicle_type: Mapped[str] = mapped_column(String(16), default="motor")

    route_from_lat: Mapped[float] = mapped_column(Float, default=0.0)
    route_from_lng: Mapped[float] = mapped_column(Float, default=0.0)
    route_to_lat: Mapped[float] = mapped_column(Float, default=0.0)
    route_to_lng: Mapped[float] = mapped_column(Float, default=0.0)

    duration_hours: Mapped[int] = mapped_column(Integer, default=6)  # 6/12/24

    # Needed for finance commission 10%
    order_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    year: Mapped[int] = mapped_column(Integer, nullable=True)

    vehicle_make: Mapped[str] = mapped_column(String(120), nullable=True)
    vehicle_model: Mapped[str] = mapped_column(String(120), nullable=True)


    commission_percent: Mapped[int] = mapped_column(Integer, default=10)

    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.bidding.value)

    # Fastest-finger first lock + tracking
    winner_driver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)

    warnings_count: Mapped[int] = mapped_column(Integer, default=0)  # MVP penalty stub


    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), onupdate=lambda: dt.datetime.now(dt.timezone.utc))

