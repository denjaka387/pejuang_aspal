from __future__ import annotations

import datetime as dt
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String

from sqlalchemy.orm import Mapped, mapped_column

from .base import Base



class FinanceSource(str):
    auction_commission = "auction_commission"
    setoran = "setoran"
    bensin = "bensin"
    makan = "makan"


class FinanceLog(Base):
    __tablename__ = "finance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    source: Mapped[str] = mapped_column(String(64), default=FinanceSource.setoran)
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # positive/negative handled by sign
    note: Mapped[str] = mapped_column(String(255), default="")

    related_order_id: Mapped[int] = mapped_column(Integer, nullable=True)


    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

