from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..models import get_session
from ..models.order import Order, OrderStatus
from ..models.user import User
from ..models.device_fingerprint import AntiFraudWarning
from ..models.finance import FinanceLog, FinanceSource

from .geo import haversine_km




@dataclass
class AuctionBroadcastTarget:
    driver_user_id: int
    sid: str



def is_user_banned(session, user: User, now: dt.datetime) -> bool:
    return bool(user.banned_until and user.banned_until > now)



def enforce_not_banned_or_403(user: User) -> tuple[bool, str | None]:
    now = dt.datetime.now(dt.timezone.utc)
    if user.banned_until and user.banned_until > now:
        return True, user.banned_reason
    return False, None



def compute_commission_percent(payload: dict[str, Any]) -> int:
    # Spec: system commission fixed 10%
    return 10


def increment_warning_and_maybe_ban(user_id: int, reason: str) -> dict[str, Any]:
    """Increment warning_count for lelang fraud/SOP violations.

    Behavior (spec):
    - record warning in DB
    - if reaches 3 warnings, ban account for 1 month
    """

    session = get_session()
    try:
        user = session.get(User, int(user_id))
        if user is None:
            return {"status": "error", "message": "user_not_found"}

        now = dt.datetime.now(dt.timezone.utc)
        # MVP: maintain a single AntiFraudWarning row per user (warning_count cumulative)
        warning_row = (
            session.execute(
                select(AntiFraudWarning).where(AntiFraudWarning.user_id == int(user_id))
            ).scalars().first()
        )

        if warning_row is None:
            warning_row = AntiFraudWarning(user_id=int(user_id), reason=reason, warning_count=1)
            session.add(warning_row)
        else:
            warning_row.warning_count = int(warning_row.warning_count or 0) + 1
            warning_row.reason = reason

        # Apply ban if warning_count >= 3
        warning_count = int(warning_row.warning_count or 0)
        banned = False
        banned_reason = None
        if warning_count >= 3:
            user.banned_until = now + dt.timedelta(days=30)
            user.banned_reason = "anti_fraud_lelang_warning_3x"
            user.is_active = False
            banned = True
            banned_reason = user.banned_reason

        session.commit()

        return {
            "status": "ok",
            "warning_count": warning_count,
            "banned": banned,
            "banned_reason": banned_reason,
        }
    finally:
        session.close()


def lock_take_order(order_id: int, driver_user_id: int, expected_status: str = OrderStatus.bidding.value) -> bool:
    """Atomic take: if order is still bidding, lock it.

    SQLite strategy: single transaction + conditional update via status check.
    """

    session = get_session()
    try:
        now = dt.datetime.now(dt.timezone.utc)

        # Load row
        order = session.get(Order, int(order_id))
        if order is None:
            return False

        if order.status != expected_status:
            return False

        # Enforce: only Mobil lelang
        if str(order.vehicle_type or "").lower() != "mobil":
            return False

        order.status = OrderStatus.ongoing.value
        order.winner_driver_user_id = int(driver_user_id)
        order.locked_at = now
        session.commit()
        return True
    finally:
        session.close()


def filter_drivers_by_radius(
    drivers_location: dict[int, Any],
    order_from_lat: float,
    order_from_lng: float,
    radius_m: float | None,
) -> list[int]:
    if radius_m is None:
        return list(drivers_location.keys())

    radius_km = float(radius_m) / 1000.0
    matched: list[int] = []

    for driver_id, loc in drivers_location.items():
        try:
            lat = float(loc.lat)
            lng = float(loc.lng)
        except Exception:
            continue

        distance_km = haversine_km(order_from_lat, order_from_lng, lat, lng)
        if distance_km <= radius_km:
            matched.append(int(driver_id))

    return matched


def maybe_record_commission_on_arrived_destination(order_id: int, driver_user_id: int) -> None:
    """Record 10% commission to finance_logs once per order.

    MVP: naive guard using FinanceLog.related_order_id+source.
    """
    session = get_session()
    try:
        # check if already recorded
        existing = (
            session.query(FinanceLog)
            .filter(
                FinanceLog.related_order_id == int(order_id),
                FinanceLog.source == FinanceSource.auction_commission,
            )
            .first()
        )
        if existing is not None:
            return

        order = session.get(Order, int(order_id))
        if order is None:
            return

        commission_percent = int(order.commission_percent or 10)
        order_amount = float(order.order_amount or 0.0)
        commission_amount = (commission_percent / 100.0) * order_amount

        log = FinanceLog(
            driver_user_id=int(driver_user_id),
            source=FinanceSource.auction_commission,
            amount=float(commission_amount),
            note=f"Komisi lelang {commission_percent}% (MVP)",
            related_order_id=int(order_id),
        )
        session.add(log)
        session.commit()
    finally:
        session.close()


def set_order_stage(order_id: int, stage: str) -> None:


    session = get_session()
    try:
        order = session.get(Order, int(order_id))
        if order is None:
            return
        # stage values map directly to Order.status allowed strings in MVP
        order.status = stage
        session.commit()
    finally:
        session.close()

