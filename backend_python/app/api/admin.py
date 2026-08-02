from __future__ import annotations

import datetime as dt
from typing import Any

from flask import Blueprint, jsonify

from ..models import get_session
from ..models.finance import FinanceLog, FinanceSource
from ..models.order import Order
from ..models.user import User
from ..sockets.online_driver_registry import online_driver_registry


admin_bp = Blueprint("admin", __name__)


def _to_iso(x: Any) -> str | None:
    if x is None:
        return None
    if isinstance(x, dt.datetime):
        return x.isoformat()
    return str(x)


@admin_bp.get("/online-drivers")
def online_drivers():
    """Return currently active drivers from OnlineDriverRegistry (in-memory, real-time).

    MVP: returns latest location snapshot per driver.
    """

    locations = online_driver_registry.get_all_locations()

    items: list[dict[str, Any]] = []
    for driver_user_id, loc in locations.items():
        items.append(
            {
                "driver_user_id": int(driver_user_id),
                "lat": float(loc.lat),
                "lng": float(loc.lng),
                "updated_at_iso": _to_iso(loc.updated_at_iso),
            }
        )

    # Sort by driver_user_id for stable response
    items.sort(key=lambda x: x["driver_user_id"])

    return jsonify({"status": "ok", "count": len(items), "drivers": items}), 200


@admin_bp.get("/finance/commission-total")
def finance_commission_total():
    """Calculate total system commission (fixed 10%) based on finance_logs.

    We treat finance_logs.source == auction_commission as system commission entries.
    """

    session = get_session()
    try:
        total = (
            session.query(FinanceLog.amount)
            .filter(FinanceLog.source == FinanceSource.auction_commission)
            .all()
        )

        total_commission = 0.0
        for (amount,) in total:
            if amount is None:
                continue
            total_commission += float(amount)

        return jsonify({"status": "ok", "commission_percent": 10, "total_commission": total_commission}), 200
    finally:
        session.close()


@admin_bp.post("/unban-driver/<int:user_id>")
def unban_driver(user_id: int):
    """Reset anti-fraud warnings and unban a driver.

    Action:
      - reset User.is_active = True
      - clear User.banned_until and banned_reason

    Note: warning_count is stored in anti_fraud_warnings table via AntiFraudWarning (MVP),
    but requirement mentions warning_count and banned_until. We clear both the ban fields
    on User and the latest warning row(s) for the user.
    """

    session = get_session()
    try:
        user = session.get(User, int(user_id))
        if user is None:
            return jsonify({"status": "error", "message": "user_not_found"}), 404

        # Clear ban on User
        user.banned_until = None
        user.banned_reason = None
        user.is_active = True

        # Clear warning rows (if table exists in model)
        try:
            from ..models.device_fingerprint import AntiFraudWarning

            session.query(AntiFraudWarning).filter(AntiFraudWarning.user_id == int(user_id)).delete(
                synchronize_session=False
            )
        except Exception:
            # If MVP table not present, still allow unban of access
            pass

        session.commit()

        return jsonify({"status": "ok", "message": "unbanned", "user_id": int(user_id)}), 200
    finally:
        session.close()

