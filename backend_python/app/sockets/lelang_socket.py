from __future__ import annotations

import datetime as dt

from flask_socketio import Namespace, emit

from ..core.rate_limiter import RateLimiter
from ..models import get_session
from ..models.order import Order, OrderStatus
from ..models.user import User
from flask import current_app

from ..core.e2e_crypto import E2ECryptoError, decrypt_envelope_json
from ..services.lelang_service import (
    increment_warning_and_maybe_ban,
    lock_take_order,
    maybe_record_commission_on_arrived_destination,
    set_order_stage,
)


rate_limiter = RateLimiter()


def _get_lelang_e2e_key_bytes() -> bytes | None:
    """Read shared AES-256 key from env/config.

    Expected base64 key length: 32 bytes after decoding.

    Server precedence:
      1) current_app.config['LELANG_E2E_KEY_B64']
      2) environment variable 'LELANG_E2E_KEY_B64'
    """

    try:
        key_b64 = current_app.config.get("LELANG_E2E_KEY_B64")
    except Exception:
        key_b64 = None

    if not key_b64:
        import os

        key_b64 = os.environ.get("LELANG_E2E_KEY_B64")

    if not key_b64:
        return None

    import base64

    try:
        key_bytes = base64.b64decode(key_b64, validate=True)
    except Exception:
        return None

    # AES-256 => 32 bytes
    if len(key_bytes) != 32:
        return None

    return key_bytes



class LelangNamespaceTest(Namespace):
    """Socket events for bidding/fastest-finger. Lives on namespace /test."""

    def on_connect(self):
        # client may listen for status
        emit("lelang_socket_connected", {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()})

    def on_driver_take_order(self, data):
        """Fastest-finger first.

        Supports two input formats:

        1) Plaintext (backward compatible)
           { order_id: int, driver_user_id: int, client_lock_token?: str }

        2) Encrypted envelope (E2E AES-256-GCM)
           {
             "enc": { "nonce": "<b64>", "ciphertext": "<b64>", "tag": "<b64>" },
             "aad": "optional"  // optional AAD string
           }

        The decrypted JSON must contain:
          { order_id: int, driver_user_id: int }
        """

        if not isinstance(data, dict):
            return

        # If payload contains encrypted envelope, decrypt first.
        if isinstance(data.get("enc"), dict):
            key_bytes = _get_lelang_e2e_key_bytes()
            if key_bytes is None:
                emit(
                    "security_error",
                    {"status": "error", "message": "e2e_key_missing_or_invalid"},
                    to=str(self),
                )
                emit(
                    "order_take_rejected",
                    {"status": "error", "message": "security_decrypt_failed"},
                    to=str(self),
                )
                return

            try:
                decrypted = decrypt_envelope_json(data, key_32=key_bytes)
            except E2ECryptoError:
                emit(
                    "security_error",
                    {"status": "error", "message": "e2e_decrypt_failed"},
                    to=str(self),
                )
                emit(
                    "order_take_rejected",
                    {"status": "error", "message": "security_decrypt_failed"},
                    to=str(self),
                )
                return

            if not isinstance(decrypted, dict):
                emit(
                    "security_error",
                    {"status": "error", "message": "e2e_decrypt_plaintext_not_dict"},
                    to=str(self),
                )
                emit(
                    "order_take_rejected",
                    {"status": "error", "message": "security_decrypt_failed"},
                    to=str(self),
                )
                return

            data = decrypted

        order_id = data.get("order_id")
        driver_user_id = data.get("driver_user_id")
        if order_id is None or driver_user_id is None:
            emit("order_take_rejected", {"status": "error", "message": "missing_fields"}, to=str(self))
            return


        # Rate limit per sid
        if not rate_limiter.allow(f"lelang:take:{getattr(self, 'sid', 'unknown')}:{driver_user_id}"):
            emit("order_take_rejected", {"status": "error", "message": "rate_limited"})
            return

        session = get_session()
        try:
            driver = session.get(User, int(driver_user_id))
            if driver is None:
                emit("order_take_rejected", {"status": "error", "message": "driver_not_found"})
                return

            now = dt.datetime.now(dt.timezone.utc)
            if driver.banned_until and driver.banned_until > now:
                emit("order_take_rejected", {"status": "error", "message": "banned"})
                return

            # Enforce: only Mobil orders & bids
            if str(driver.vehicle_type or "").lower().strip() != "mobil":
                emit("order_take_rejected", {"status": "error", "message": "driver_not_mobil"})
                return

        finally:
            session.close()

        locked = lock_take_order(int(order_id), int(driver_user_id), expected_status=OrderStatus.bidding.value)

        if locked:
            emit(
                "order_dimenangkan",
                {
                    "status": "ok",
                    "order_id": int(order_id),
                    "driver_user_id": int(driver_user_id),
                    "t": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )


            # Notify all other connected clients in /test: since we don't have per-filter rooms yet,
            # broadcast globally with target data and clients will ignore mismatched driver_user_id.
            emit(
                "order_sudah_diambil",
                {
                    "status": "taken",
                    "order_id": int(order_id),
                    "winner_driver_user_id": int(driver_user_id),
                    "t": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
                namespace="/test",
            )
        else:
            emit(
                "order_take_rejected",
                {
                    "status": "error",
                    "message": "already_taken_or_not_bidding",
                    "order_id": int(order_id),
                },
            )

    def on_driver_stage_update(self, data):
        """Update stage tracking.

        Expected:
          { order_id, driver_user_id, stage }
        Stage values follow OrderStatus enum:
          to_pickup -> arrived_pickup -> on_trip -> arrived_destination -> back_to_start
        """

        if not isinstance(data, dict):
            return

        order_id = data.get("order_id")
        driver_user_id = data.get("driver_user_id")
        stage = data.get("stage")
        if order_id is None or driver_user_id is None or stage is None:
            emit("order_stage_update_rejected", {"status": "error", "message": "missing_fields"})
            return

        # Only allow stage update by the winning driver
        session = get_session()
        try:
            order = session.get(Order, int(order_id))
            if order is None:
                emit("order_stage_update_rejected", {"status": "error", "message": "order_not_found"})
                return

            if order.winner_driver_user_id is None or int(order.winner_driver_user_id) != int(driver_user_id):
                emit(
                    "order_stage_update_rejected",
                    {"status": "error", "message": "not_winner_driver"},
                )
                return

            driver = session.get(User, int(driver_user_id))
            if driver is None:
                emit("order_stage_update_rejected", {"status": "error", "message": "driver_not_found"})
                return

            now = dt.datetime.now(dt.timezone.utc)
            if driver.banned_until and driver.banned_until > now:
                emit("order_stage_update_rejected", {"status": "error", "message": "banned"})
                return

        finally:
            session.close()

        # Restrict to mobil only (driver side)
        locked = str(stage).strip() in {s.value for s in OrderStatus}
        if not locked:
            emit("order_stage_update_rejected", {"status": "error", "message": "invalid_stage"})
            return

        set_order_stage(int(order_id), str(stage))

        if str(stage) == OrderStatus.arrived_destination.value:
            maybe_record_commission_on_arrived_destination(int(order_id), int(driver_user_id))

        emit(
            "order_stage_updated",
            {
                "status": "ok",
                "order_id": int(order_id),
                "driver_user_id": int(driver_user_id),
                "stage": str(stage),
                "t": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            namespace="/test",
        )

    def on_driver_cancel_order(self, data):

        """Driver cancels after winning (anti-fraud warning MVP).

        Expected:
          { order_id, driver_user_id, reason }
        """

        if not isinstance(data, dict):
            return

        order_id = data.get("order_id")
        driver_user_id = data.get("driver_user_id")
        reason = str(data.get("reason") or "driver_cancel")
        if order_id is None or driver_user_id is None:
            return

        res = increment_warning_and_maybe_ban(int(driver_user_id), reason=reason)
        emit(
            "order_warning_result",
            {
                "status": "ok",
                "order_id": int(order_id),
                "driver_user_id": int(driver_user_id),
                "warning_count": res.get("warning_count"),
                "banned": res.get("banned"),
                "banned_reason": res.get("banned_reason"),
            },
        )


def register_lelang_socket_namespace_test(socketio) -> None:
    socketio.on_namespace(LelangNamespaceTest("/test"))

