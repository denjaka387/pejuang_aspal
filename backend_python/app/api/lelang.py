from __future__ import annotations

import datetime as dt

from flask import Blueprint, jsonify, request

from .. import get_socketio
from ..models import get_session
from ..models.order import Order, OrderStatus
from ..models.user import User
from ..models.device_fingerprint import SubscriptionTrial
from ..services.lelang_service import compute_commission_percent, enforce_not_banned_or_403


lelang_bp = Blueprint("lelang", __name__)


@lelang_bp.post("/orders")
def create_order():
    """Create Auction/ Lelang Order and broadcast pop-up.

    Spec payload (minimal fields used):
      - user_id (creator)
      - passenger_name, passenger_contact
      - route_from_lat/lng, route_to_lat/lng
      - auction_duration_hours: 6/12/24
      - vehicle_type: must be 'mobil' only
      - auction_year
      - radius_m

    Commission: fixed 10% automatic transfer.

    Broadcast: via socket namespace /test.
    """

    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id")

    if user_id is None:
        return jsonify({"status": "error", "message": "missing_user_id"}), 400

    session = get_session()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            return jsonify({"status": "error", "message": "user_not_found"}), 404

        now = dt.datetime.now(dt.timezone.utc)
        banned, banned_reason = enforce_not_banned_or_403(user)
        if banned:
            return jsonify({"status": "error", "message": "banned", "banned_reason": banned_reason}), 403

        premium_active = bool(user.premium_until and user.premium_until > now)
        trial = session.query(SubscriptionTrial).filter(SubscriptionTrial.user_id == user.id).first()
        trial_active = bool(trial and trial.is_active and trial.trial_expires_at and trial.trial_expires_at > now)

        if not premium_active and not trial_active:
            return jsonify({"status": "error", "message": "Masa Trial Habis", "action": "go_to_premium"}), 402

        vehicle_type = str(payload.get("vehicle_type") or "").lower().strip()
        if vehicle_type != "mobil":
            return jsonify({"status": "error", "message": "lelang_order_only_mobil"}), 400

        duration_hours = int(payload.get("auction_duration_hours") or 6)
        if duration_hours not in (6, 12, 24):
            return jsonify({"status": "error", "message": "invalid_auction_duration_hours"}), 400

        order = Order(
            created_by_user_id=user.id,
            passenger_name=str(payload.get("passenger_name") or ""),
            passenger_contact=str(payload.get("passenger_contact") or ""),
            vehicle_type="mobil",
            route_from_lat=float(payload.get("route_from_lat") or 0.0),
            route_from_lng=float(payload.get("route_from_lng") or 0.0),
            route_to_lat=float(payload.get("route_to_lat") or 0.0),
            route_to_lng=float(payload.get("route_to_lng") or 0.0),
            duration_hours=duration_hours,
            year=payload.get("auction_year"),
            vehicle_make=payload.get("vehicle_make"),
            vehicle_model=payload.get("vehicle_model"),
            commission_percent=compute_commission_percent(payload),
            order_amount=float(payload.get("order_amount") or 0.0),
            status=OrderStatus.bidding.value,
        )


        session.add(order)
        session.commit()

        socketio = get_socketio(request.app)


        # Broadcast pop-up only for mobil; geofence/radius computed on socket side (MVP placeholder)
        order_payload = {
            "order_id": order.id,
            "vehicle_type": "mobil",
            "radius_m": payload.get("radius_m"),
            "duration_hours": order.duration_hours,
            "auction_year": order.year,
            "passenger_name": order.passenger_name,
            "passenger_contact": order.passenger_contact,
            "route_from_lat": order.route_from_lat,
            "route_from_lng": order.route_from_lng,
            "route_to_lat": order.route_to_lat,
            "route_to_lng": order.route_to_lng,
            "commission_percent": order.commission_percent,
            "t": now.isoformat(),
        }

        # Radius filtering: send only to drivers with current location within order.radius_m
        try:
            from ..sockets.online_driver_registry import online_driver_registry
            from ..services.lelang_service import filter_drivers_by_radius

            radius_m_value = payload.get("radius_m")
            all_locations = online_driver_registry.get_all_locations()
            matched_driver_ids = filter_drivers_by_radius(
                all_locations,
                order.route_from_lat,
                order.route_from_lng,
                radius_m_value,
            )

            # MVP socketio: no per-driver room; send broadcast but with client-side ignore.
            # For now, include matched list so clients can decide locally.
            order_payload["matched_driver_ids"] = matched_driver_ids
        except Exception:
            # fallback: keep matched empty list
            order_payload["matched_driver_ids"] = []


    finally:
        session.close()

    # Emit to /test namespace
    socketio.emit("lelang_pop_up", order_payload, namespace="/test")

    return jsonify({"status": "ok", "message": "order_created", "order_id": order.id}), 201


@lelang_bp.get("/orders/<int:order_id>")
def get_order(order_id: int):
    session = get_session()
    try:
        order = session.get(Order, int(order_id))
        if order is None:
            return jsonify({"status": "error", "message": "order_not_found"}), 404

        return jsonify(
            {
                "status": "ok",
                "order": {
                    "order_id": order.id,
                    "vehicle_type": order.vehicle_type,
                    "status": order.status,
                    "duration_hours": order.duration_hours,
                    "auction_year": order.year,
                    "commission_percent": order.commission_percent,
                },
            }
        )
    finally:
        session.close()


