from __future__ import annotations

import datetime as dt

from flask import request
from flask_socketio import Namespace, emit

from ..core.rate_limiter import RateLimiter
from ..models import get_session
from ..models.user import User

rate_limiter = RateLimiter()


class SosNamespace(Namespace):
    """Namespace /sos: high-priority panic/SOS alerts.

    MVP contract:
      client emits:  panic { user_id: int, message?: str }
      server emits: sos_alert { status, from_user_id, message, t }

    IMPORTANT: This namespace is isolated from /chat and /radar to prevent
    Walkie-Talkie traffic from impacting SOS listeners.

    MVP contract (updated):
      client emits:  panic { user_id: int, message?: str, lat?: float, lng?: float }
      server emits: sos_alert { status, from_user_id, message, lat?: float, lng?: float, t }
    """


    def on_connect(self):
        emit(
            "sos_connected",
            {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()},
        )

    def on_panic(self, data):
        if not isinstance(data, dict):
            return

        user_id = data.get("user_id")
        message = (data.get("message") or "Panic SOS").strip()

        if user_id is None:
            emit("sos_alert", {"status": "error", "message": "missing_user_id"})
            return

        # Rate limit per sid
        if not rate_limiter.allow(f"sos:panic:{getattr(request, 'sid', 'unknown')}:{user_id}"):
            emit(
                "sos_alert",
                {"status": "error", "message": "rate_limited"},
            )
            return

        session = get_session()
        try:
            user = session.get(User, int(user_id))
            if user is None:
                emit(
                    "sos_alert",
                    {"status": "error", "message": "user_not_found"},
                )
                return

            now = dt.datetime.now(dt.timezone.utc)
            if user.banned_until and user.banned_until > now:
                emit(
                    "sos_alert",
                    {"status": "error", "message": "banned"},
                )
                return

        finally:
            session.close()

        # Lat/Lng are optional for MVP; if provided, include them in sos_alert payload.
        lat = data.get("lat")
        lng = data.get("lng")


        # For now: MVP broadcast within /sos.

        # Later: replace emit(broadcast) with targeted room emits based on geofencing.

        emit(
            "sos_alert",
            {
                "status": "ok",
                "from_user_id": int(user_id),
                "message": message,
                "lat": float(lat) if lat is not None else None,
                "lng": float(lng) if lng is not None else None,
                "t": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            namespace="/sos",
        )


    def on_sos_ack(self, data):
        """Optional acknowledge from client."""
        if not isinstance(data, dict):
            return

        user_id = data.get("user_id")

        if user_id is None:
            return

        emit(
            "sos_ack",
            {
                "status": "ok",
                "user_id": int(user_id),
                "t": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            namespace="/sos",
        )


def register_sos_namespace(socketio) -> None:
    socketio.on_namespace(SosNamespace("/sos"))

