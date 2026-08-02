from __future__ import annotations

import datetime as dt

from flask import request
from flask_socketio import Namespace, emit

from ..core.rate_limiter import RateLimiter
from ..core.rate_limiter_advanced import RateLimiterAdvanced, make_burst_controller


from ..models import get_session
from ..models.user import User

from ..services.geo import haversine_km


# Socket-level rate limiter (MVP/in-memory). NOTE: requirement for flask-limiter
# is handled separately for REST endpoints.
rate_limiter = RateLimiter()


# In-memory latest location state for fraud detection.
# Keyed by user_id.
_location_history: dict[int, dict] = {}


def _clamp_float(x: object, default: float) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _validate_lat_lng(lat: float, lng: float) -> bool:
    return (-90.0 <= lat <= 90.0) and (-180.0 <= lng <= 180.0)


def _is_mock_or_inaccurate(data: dict) -> tuple[bool, str | None]:
    """Return (is_mock, reason)."""
    accuracy_m = _clamp_float(data.get("accuracy_m"), 999.0)

    # Heuristic: very poor accuracy usually means mock/incorrect GPS.
    if accuracy_m > 80:
        return True, "accuracy_too_bad"

    # Client can explicitly send a mock flag.
    if data.get("mock_location_detected") is True:
        return True, "client_mock_flag"

    # Extreme speed values are suspicious.
    speed_kmh = _clamp_float(data.get("speed_kmh"), 0.0)
    if speed_kmh > 200:
        return True, "client_speed_too_high"

    return False, None


def _fraud_speed_check(user_id: int, lat: float, lng: float, now: dt.datetime, accuracy_m: float, speed_kmh: float) -> tuple[bool, str | None]:
    """Detect physically impossible jumps.

    Strategy:
    - Keep last coordinate for each user.
    - Compute haversine distance.
    - Compute implied speed = distance_km / delta_hours.
    - Reject if implied speed exceeds a conservative max.
    """

    prev = _location_history.get(int(user_id))
    if not prev:
        _location_history[int(user_id)] = {
            "lat": lat,
            "lng": lng,
            "t": now,
            "accuracy_m": accuracy_m,
            "speed_kmh": speed_kmh,
        }
        return False, None

    try:
        prev_lat = float(prev["lat"])
        prev_lng = float(prev["lng"])
        prev_t = prev["t"]
        if not isinstance(prev_t, dt.datetime):
            prev_t = now
    except Exception:
        prev_lat, prev_lng, prev_t = lat, lng, now

    delta_s = (now - prev_t).total_seconds()
    if delta_s <= 0:
        # ignore out-of-order timestamps
        return False, None

    # Avoid being overly sensitive to normal movement when updates are noisy.
    # If updates come extremely frequently, still require realistic speed.
    delta_hours = delta_s / 3600.0

    dist_km = haversine_km(prev_lat, prev_lng, lat, lng)
    implied_speed_kmh = dist_km / delta_hours if delta_hours > 0 else 0.0

    # Conservative upper bounds for ride-hailing drivers.
    MAX_REASONABLE_SPEED_KMH = 180.0

    # Extra guard: if distance is large and time window is tiny.
    # (e.g. teleporting several km in <10s)
    if implied_speed_kmh > MAX_REASONABLE_SPEED_KMH:
        # update state even on fraud attempt so we don't keep comparing old coords forever
        _location_history[int(user_id)] = {
            "lat": lat,
            "lng": lng,
            "t": now,
            "accuracy_m": accuracy_m,
            "speed_kmh": speed_kmh,
        }
        return True, "implied_speed_too_high"

    # Update history on valid moves
    _location_history[int(user_id)] = {
        "lat": lat,
        "lng": lng,
        "t": now,
        "accuracy_m": accuracy_m,
        "speed_kmh": speed_kmh,
    }

    return False, None


def process_radar_location_update(
    *,
    data: dict,
    session,
    emit_geofence: bool,
    fraud_emit: bool,
):
    """Shared processing for both Socket.IO update_location and REST POST.

    Returns a dict with:
    - ok: bool
    - error_message: str | None
    - geofence_payload: dict | None
    - fraud_payload: dict | None
    """

    user_id_raw = data.get("user_id")
    if user_id_raw is None:
        return {"ok": False, "error_message": "missing_user_id", "geofence_payload": None, "fraud_payload": None}

    try:
        user_id = int(user_id_raw)
    except Exception:
        return {"ok": False, "error_message": "invalid_user_id", "geofence_payload": None, "fraud_payload": None}

    lat = float(data.get("lat", 0.0))
    lng = float(data.get("lng", 0.0))
    accuracy_m = float(data.get("accuracy_m", 999.0))
    speed_kmh = float(data.get("speed_kmh", 0.0))
    bearing = data.get("bearing")

    # Validate coordinates
    if not _validate_lat_lng(lat, lng):
        return {"ok": False, "error_message": "invalid_lat_lng", "geofence_payload": None, "fraud_payload": None}

    # Load user
    user = session.get(User, user_id)
    if user is None:
        return {"ok": False, "error_message": "user_not_found", "geofence_payload": None, "fraud_payload": None}

    now = dt.datetime.now(dt.timezone.utc)
    if user.banned_until and user.banned_until > now:
        return {"ok": False, "error_message": "banned", "geofence_payload": None, "fraud_payload": None}

    # 1) Fake GPS / Mock location checks
    is_mock, mock_reason = _is_mock_or_inaccurate(data)

    # 2) Fraud checks based on implied speed between updates
    is_speed_fraud, speed_reason = _fraud_speed_check(
        user_id,
        lat=lat,
        lng=lng,
        now=now,
        accuracy_m=accuracy_m,
        speed_kmh=speed_kmh,
    )

    if is_mock or is_speed_fraud:
        # Persist ban
        user.mock_location_detected = True
        user.banned_until = now + dt.timedelta(hours=24)

        reasons: list[str] = []
        if mock_reason:
            reasons.append(f"mock:{mock_reason}")
        if speed_reason:
            reasons.append(f"speed:{speed_reason}")

        user.banned_reason = ";".join(reasons) if reasons else "geo_fraud_detected"
        session.commit()

        fraud_payload = {
            "status": "error",
            "message": "fake_gps_banned_24h",
            "user_id": int(user.id),
            "reason": user.banned_reason,
            "banned_until": user.banned_until.isoformat() if user.banned_until else None,
        }
        return {
            "ok": False,
            "error_message": "geo_fraud_detected",
            "geofence_payload": None,
            "fraud_payload": fraud_payload,
        }


    # Update online location registry (used by lelang radius filtering)
    try:
        from .online_driver_registry import online_driver_registry

        if user.vehicle_type and str(user.vehicle_type).lower().strip() == "mobil":
            online_driver_registry.set_location(
                int(user.id),
                lat,
                lng,
                dt.datetime.now(dt.timezone.utc).isoformat(),
                user.app_ecosystem or "",
            )
    except Exception:
        pass

    # Geofence stub: include nearby drivers within fixed radius (stub: 200m).
    nearby_drivers: list[dict] = []
    try:
        radius_m = 200.0
        from .online_driver_registry import online_driver_registry

        for other_id, loc in online_driver_registry.get_all_locations().items():
            if int(other_id) == int(user.id):
                continue

            dist_km = haversine_km(lat1=loc.lat, lon1=loc.lng, lat2=lat, lon2=lng)
            dist_m = dist_km * 1000.0
            if dist_m <= radius_m:
                nearby_drivers.append(
                    {
                        "user_id": int(other_id),
                        "lat": float(loc.lat),
                        "lng": float(loc.lng),
                        "app_ecosystem": loc.app_ecosystem or "",
                        "updated_at_iso": loc.updated_at_iso,
                    }
                )
    except Exception:
        nearby_drivers = []

    geofence_payload = {
        "status": "ok",
        "lat": lat,
        "lng": lng,
        "accuracy_m": accuracy_m,
        "speed_kmh": speed_kmh,
        "bearing": bearing,
        "nearby_drivers": nearby_drivers,
    }

    return {"ok": True, "error_message": None, "geofence_payload": geofence_payload, "fraud_payload": None}


class RadarNamespace(Namespace):
    """Namespace /radar: update lokasi, geofencing stub, fake gps detection stub."""

    def on_connect(self):
        # Anda bisa melakukan join_room berbasis user_id untuk emit targeted.
        # Untuk MVP ini, cukup beri sinyal connected.
        emit("radar_connected", {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()})

    def on_update_location(self, data):
        # Reuse shared processing logic.

        # MVP expected payload:
        # { user_id, lat, lng, accuracy_m, speed_kmh, bearing }
        if not isinstance(data, dict):
            return

        # Burst control per-sid + sustained control per-user_id.
        sid = getattr(request, "sid", None) or getattr(self, "sid", None) or "unknown"
        user_id_raw = data.get("user_id")
        user_id_for_rate: int | None
        try:
            user_id_for_rate = int(user_id_raw) if user_id_raw is not None else None
        except Exception:
            user_id_for_rate = None

        # Per-sid: 10 events / 10s (burst + refill 1 token/sec)
        if not rate_limiter.allow(
            f"radar:update_location:sid:{sid}",
            capacity=10,
            refill_per_sec=1.0,
        ):
            emit("rate_limited", {"status": "error", "message": "Rate limited (sid burst)"})
            return

        # Per-user: 30 events / 60s
        if user_id_for_rate is not None:
            if not rate_limiter.allow(
                f"radar:update_location:user:{user_id_for_rate}",
                capacity=30,
                refill_per_sec=0.5,
            ):
                emit("rate_limited_user", {"status": "error", "message": "Rate limited (user)"})
                return



        user_id = data.get("user_id")
        lat = float(data.get("lat", 0.0))
        lng = float(data.get("lng", 0.0))
        accuracy_m = float(data.get("accuracy_m", 999.0))
        speed_kmh = float(data.get("speed_kmh", 0.0))
        bearing = data.get("bearing")

        session = get_session()
        try:
            user = session.get(User, int(user_id)) if user_id is not None else None
            if user is None:
                emit("radar_error", {"status": "error", "message": "user_not_found"})
                return

            now = dt.datetime.now(dt.timezone.utc)
            if user.banned_until and user.banned_until > now:
                emit(
                    "radar_error",
                    {"status": "error", "message": "banned"},
                )
                return

            # Validate coordinates
            if not _validate_lat_lng(lat, lng):
                emit(
                    "radar_error",
                    {"status": "error", "message": "invalid_lat_lng"},
                )
                return

            # 1) Fake GPS / Mock location checks
            is_mock, mock_reason = _is_mock_or_inaccurate(data)

            # 2) Fraud checks based on implied speed between updates
            is_speed_fraud, speed_reason = _fraud_speed_check(
                int(user.id),
                lat=lat,
                lng=lng,
                now=now,
                accuracy_m=accuracy_m,
                speed_kmh=speed_kmh,
            )

            if is_mock or is_speed_fraud:
                # Persist ban
                user.mock_location_detected = True
                user.banned_until = now + dt.timedelta(hours=24)

                # Build reason
                reasons: list[str] = []
                if mock_reason:
                    reasons.append(f"mock:{mock_reason}")
                if speed_reason:
                    reasons.append(f"speed:{speed_reason}")

                user.banned_reason = ";".join(reasons) if reasons else "geo_fraud_detected"

                session.commit()

                # Broadcast fraud event ke semua client yang sedang listening di namespace /radar.
                # (emit dengan room user_id membutuhkan join_room; agar robust gunakan namespace broadcast.)
                emit(
                    "fraud_detected",
                    {
                        "status": "error",
                        "message": "fake_gps_banned_24h",
                        "user_id": int(user.id),
                        "reason": user.banned_reason,
                        "banned_until": user.banned_until.isoformat() if user.banned_until else None,
                    },
                    namespace="/radar",
                )
                return

            # Geofence stub: just echo back
            # Update online location registry (used by lelang radius filtering)
            try:
                from .online_driver_registry import online_driver_registry


                # Store driver location + ecosystem in in-memory registry.
                # MVP: keep same vehicle_type gate as existing code.
                if user.vehicle_type and str(user.vehicle_type).lower().strip() == "mobil":
                    online_driver_registry.set_location(
                        int(user.id),
                        lat,
                        lng,
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                        user.app_ecosystem or "",
                    )

            except Exception:
                pass

            # MVP geofence cross-check: include nearby drivers within fixed radius (stub: 200m).
            # This keeps payload size bounded and rendering predictable.
            try:
                radius_m = 200.0
                nearby_drivers: list[dict] = []

                from .online_driver_registry import online_driver_registry

                for other_id, loc in online_driver_registry.get_all_locations().items():
                    if int(other_id) == int(user.id):
                        continue

                    dist_km = haversine_km(lat1=loc.lat, lon1=loc.lng, lat2=lat, lon2=lng)  # best-effort

                    dist_m = dist_km * 1000.0
                    if dist_m <= radius_m:
                        nearby_drivers.append(
                            {
                                "user_id": int(other_id),
                                "lat": float(loc.lat),
                                "lng": float(loc.lng),
                                "app_ecosystem": loc.app_ecosystem or "",
                                "updated_at_iso": loc.updated_at_iso,
                            }
                        )
            except Exception:
                nearby_drivers = []

            emit(
                "geofence_update",
                {
                    "status": "ok",
                    "lat": lat,
                    "lng": lng,
                    "accuracy_m": accuracy_m,
                    "speed_kmh": speed_kmh,
                    "bearing": bearing,
                    "nearby_drivers": nearby_drivers,
                },
            )



        finally:
            session.close()


def register_radar_namespace(socketio):
    socketio.on_namespace(RadarNamespace("/radar"))



