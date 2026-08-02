"""
REST API endpoint untuk SOS emergency alerts (FCM push notification).

Ketika Flutter mengirim POST /api/sos, backend Flask akan:
1. Fetch semua FCM tokens dari Firestore collection driver_locations
2. Kirim FCM multicast message via Firebase Admin SDK
3. Cleanup invalid tokens
4. Return response ke Flutter

Alur ini menggantikan Firebase Cloud Functions (functions/index.js)
karena kita tidak menggunakan Blaze plan.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore, messaging
from flask import Blueprint, jsonify, request

from ..core.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)
sos_bp = Blueprint("sos", __name__)
rate_limiter = RateLimiter()


def _init_firebase_admin() -> bool:
    """Initialize Firebase Admin SDK if not already initialized.

    Uses firebase_key.json in the backend root directory.
    Returns True if successful, False otherwise.
    """
    if firebase_admin._apps:
        return True

    try:
        # Look for firebase_key.json relative to this file's location
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate up to backend_python/ root (app/api/sos.py -> app/ -> backend_python/)
        project_root = os.path.dirname(os.path.dirname(base_dir))  # backend_python/
        key_path = os.path.join(project_root, "firebase_key.json")

        if not os.path.isfile(key_path):
            logger.error(f"[sos_api] Firebase key not found at: {key_path}")
            return False

        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
        logger.info("[sos_api] Firebase Admin SDK initialized successfully")
        return True
    except Exception as e:
        logger.error(f"[sos_api] Failed to initialize Firebase Admin SDK: {e}")
        return False


def _get_firestore_db():
    """Get Firestore client (lazy init)."""
    if not _init_firebase_admin():
        return None
    return firestore.client()


def _get_victim_name(from_user_id: int) -> str:
    """Fetch victim's display name from Firestore driver_profiles."""
    try:
        db = _get_firestore_db()
        if db is None:
            return f"Driver #{from_user_id}"

        doc_ref = db.collection("driver_profiles").document(str(from_user_id))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("display_name") or data.get("displayName") or f"Driver #{from_user_id}"
    except Exception as e:
        logger.warning(f"[sos_api] Failed to fetch victim profile for {from_user_id}: {e}")

    return f"Driver #{from_user_id}"


@sos_bp.post("/send")
def send_sos_notification():
    """Endpoint untuk mengirim FCM notification ke semua driver.

    Diterima dari Flutter SosScreen setelah SOS alert dibuat di Firestore.

    Expected JSON payload:
    {
        "from_user_id": int (victim's userId),
        "from_user_name": str (optional, victim's display name),
        "message": str (optional, SOS message),
        "category": str (optional, e.g. "Ban Bocor", "Lainnya"),
        "lat": float (victim's latitude),
        "lng": float (victim's longitude),
        "alert_id": str (optional, Firestore document ID)
    }

    Returns:
    {
        "status": "ok" | "error",
        "sent_count": int,
        "failure_count": int,
        "total_tokens": int,
        "message": str (optional)
    }
    """
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    from_user_id = data.get("from_user_id")
    from_user_name = data.get("from_user_name")
    message = data.get("message") or ""
    category = data.get("category") or "Lainnya"
    lat = data.get("lat")
    lng = data.get("lng")
    alert_id = data.get("alert_id")

    # Validate required fields
    if from_user_id is None:
        return jsonify({"status": "error", "message": "missing_from_user_id"}), 400

    if lat is None or lng is None:
        return jsonify({"status": "error", "message": "missing_location"}), 400

    # Rate limit: max 3 SOS sends per user per 5 minutes
    rate_key = f"sos:send:{from_user_id}"
    if not rate_limiter.allow(rate_key, capacity=3, refill_per_sec=1.0 / 60.0):  # 3 per 5 min
        logger.warning(f"[sos_api] Rate limited for user {from_user_id}")
        return jsonify({"status": "error", "message": "rate_limited"}), 429

    logger.info(
        f"[sos_api] SOS alert from userId={from_user_id} at {lat},{lng}, category={category}"
    )

    # Initialize Firebase Admin SDK
    if not _init_firebase_admin():
        return jsonify({"status": "error", "message": "firebase_not_initialized"}), 500

    try:
        # Get victim display name
        victim_name = from_user_name or _get_victim_name(int(from_user_id))

        # Fetch all driver FCM tokens (except the victim)
        db = _get_firestore_db()
        if db is None:
            return jsonify({"status": "error", "message": "firestore_unavailable"}), 500

        drivers_snapshot = db.collection("driver_locations").get()
        tokens: list[str] = []

        for doc in drivers_snapshot.docs:
            doc_data = doc.to_dict()
            driver_id = int(doc.id)
            fcm_token = doc_data.get("fcm_token")

            # Skip the victim and drivers without FCM token
            if driver_id == int(from_user_id) or not fcm_token:
                continue

            tokens.append(fcm_token)

        if not tokens:
            logger.warning("[sos_api] No other drivers with FCM tokens found")
            return jsonify({
                "status": "ok",
                "sent_count": 0,
                "failure_count": 0,
                "total_tokens": 0,
                "message": "no_other_drivers_found",
            })

        logger.info(f"[sos_api] Sending to {len(tokens)} nearby drivers")

        # Build the FCM data message payload (sama seperti Cloud Functions)
        payload = messaging.MulticastMessage(
            data={
                "type": "sos_alert",
                "from_user_id": str(from_user_id),
                "victim_name": victim_name,
                "category": category,
                "message": message,
                "lat": str(lat),
                "lng": str(lng),
                "alert_id": alert_id or str(dt.datetime.now(dt.timezone.utc).timestamp()),
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
            },
            tokens=tokens,
        )

        # Send multicast message to all drivers
        response = messaging.send_each_for_multicast(payload)

        logger.info(
            f"[sos_api] Sent to {response.success_count} devices, {response.failure_count} failures"
        )

        # Clean up invalid/expired tokens
        if response.failure_count > 0:
            invalid_tokens: list[str] = []
            for i, resp in enumerate(response.responses):
                if not resp.success:
                    logger.warning(
                        f"[sos_api] Failed to send to token at index {i}: {resp.exception}"
                    )

                    if resp.exception and (
                        "registration-token-not-registered" in str(resp.exception)
                        or "invalid-registration-token" in str(resp.exception)
                    ):
                        invalid_tokens.append(tokens[i])

            # Remove invalid tokens from Firestore
            if invalid_tokens:
                logger.info(
                    f"[sos_api] Cleaning up {len(invalid_tokens)} invalid tokens"
                )
                for doc in drivers_snapshot.docs:
                    doc_data = doc.to_dict()
                    fcm_token = doc_data.get("fcm_token")
                    if fcm_token and fcm_token in invalid_tokens:
                        logger.warning(
                            f"[sos_api] Removing invalid token for driver {doc.id}"
                        )
                        doc.reference.update({
                            "fcm_token": firestore.DELETE_FIELD,
                            "fcm_token_invalidated_at": firestore.SERVER_TIMESTAMP,
                        })

        return jsonify({
            "status": "ok",
            "sent_count": response.success_count,
            "failure_count": response.failure_count,
            "total_tokens": len(tokens),
        })

    except Exception as e:
        logger.error(f"[sos_api] Failed to send notifications: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@sos_bp.post("/resolve")
def resolve_sos():
    """Endpoint untuk memberitahu semua driver bahwa SOS telah selesai/ditutup.

    Dipanggil dari Flutter saat driver menekan tombol 'Tutup SOS' / 'Selesaikan'.
    Backend akan mengirim FCM notification type 'sos_resolved' ke semua driver
    lain (kecuali pengirim) agar pop-up SOS otomatis tertutup di layar mereka.

    Expected JSON payload:
    {
        "from_user_id": int (victim's userId yang menutup SOS),
        "from_user_name": str (optional, victim's display name),
        "alert_id": str (Firestore document ID dari SOS alert yang di-resolve)
    }

    Returns:
    {
        "status": "ok" | "error",
        "sent_count": int,
        "failure_count": int,
        "total_tokens": int,
        "message": str (optional)
    }
    """
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    from_user_id = data.get("from_user_id")
    from_user_name = data.get("from_user_name")
    alert_id = data.get("alert_id", "")

    # Validate required fields
    if from_user_id is None:
        return jsonify({"status": "error", "message": "missing_from_user_id"}), 400

    # Rate limit: max 10 resolves per user per minute (generous karena resolve jarang terjadi)
    rate_key = f"sos:resolve:{from_user_id}"
    if not rate_limiter.allow(rate_key, capacity=10, refill_per_sec=2.0):  # 10 per ~5 detik
        logger.warning(f"[sos_api] Resolve rate limited for user {from_user_id}")
        return jsonify({"status": "error", "message": "rate_limited"}), 429

    logger.info(f"[sos_api] SOS resolved by userId={from_user_id}, alert_id={alert_id}")

    # Initialize Firebase Admin SDK
    if not _init_firebase_admin():
        return jsonify({"status": "error", "message": "firebase_not_initialized"}), 500

    try:
        # Get victim display name
        victim_name = from_user_name or _get_victim_name(int(from_user_id))

        # Fetch all FCM tokens except the victim
        db = _get_firestore_db()
        if db is None:
            return jsonify({"status": "error", "message": "firestore_unavailable"}), 500

        drivers_snapshot = db.collection("driver_locations").get()
        tokens: list[str] = []

        for doc in drivers_snapshot.docs:
            doc_data = doc.to_dict()
            driver_id = int(doc.id)
            fcm_token = doc_data.get("fcm_token")

            # Skip the victim and drivers without FCM token
            if driver_id == int(from_user_id) or not fcm_token:
                continue

            tokens.append(fcm_token)

        if not tokens:
            logger.warning("[sos_api] No other drivers with FCM tokens for resolve notification")
            return jsonify({
                "status": "ok",
                "sent_count": 0,
                "failure_count": 0,
                "total_tokens": 0,
                "message": "no_other_drivers_found",
            })

        logger.info(f"[sos_api] Sending resolve notification to {len(tokens)} drivers")

        # Build FCM data message payload for resolved SOS
        payload = messaging.MulticastMessage(
            data={
                "type": "sos_resolved",
                "from_user_id": str(from_user_id),
                "victim_name": victim_name,
                "alert_id": alert_id or str(dt.datetime.now(dt.timezone.utc).timestamp()),
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
            },
            tokens=tokens,
        )

        # Send multicast message
        response = messaging.send_each_for_multicast(payload)

        logger.info(
            f"[sos_api] Resolve notification sent to {response.success_count} devices, "
            f"{response.failure_count} failures"
        )

        return jsonify({
            "status": "ok",
            "sent_count": response.success_count,
            "failure_count": response.failure_count,
            "total_tokens": len(tokens),
        })

    except Exception as e:
        logger.error(f"[sos_api] Failed to send resolve notifications: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

