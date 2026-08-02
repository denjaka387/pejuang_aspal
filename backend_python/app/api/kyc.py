from __future__ import annotations

import datetime as dt
from flask import Blueprint, jsonify, request

kyc_bp = Blueprint("kyc", __name__)


@kyc_bp.post("/verify")
def verify_kyc():
    # MVP stub: accept KTP/selfie/SIM/WhatsApp + ride-hailing screenshot.
    payload = request.get_json(silent=True) or {}

    user_id = payload.get("user_id")
    kyc_success = bool(payload.get("kyc_success", True))

    if kyc_success and user_id is not None:
        # Inline start trial to avoid circular imports.
        from ..models import get_session
        from ..models.user import User
        from ..models.device_fingerprint import SubscriptionTrial

        def _normalize_app_ecosystem(raw: object) -> str:
            """Normalize app ecosystem into CSV string.

            Accepts:
              - CSV string: "gojek,grab"
              - list[str]: ["gojek","grab"]
            Output: lowercase CSV without duplicates.
            """
            if raw is None:
                return ""

            apps: list[str] = []
            if isinstance(raw, str):
                apps = raw.split(",")
            elif isinstance(raw, list):
                for item in raw:
                    if item is None:
                        continue
                    apps.append(str(item))
            else:
                apps = str(raw).split(",")

            cleaned: list[str] = []
            seen: set[str] = set()
            for a in apps:
                s = str(a).strip().lower()
                if not s:
                    continue
                if s in seen:
                    continue
                seen.add(s)
                cleaned.append(s)

            return ",".join(cleaned)

        # Parse ecosystem from payload (MVP)
        raw_ecosystem = payload.get("app_ecosystem", payload.get("selected_apps"))
        normalized_ecosystem = _normalize_app_ecosystem(raw_ecosystem)

        session = get_session()
        try:
            user = session.query(User).filter(User.id == int(user_id)).first()
            if user is not None:
                if normalized_ecosystem:
                    user.app_ecosystem = normalized_ecosystem

                now = dt.datetime.now(dt.timezone.utc)
                trial_expires_at = now + dt.timedelta(days=30)

                trial = (
                    session.query(SubscriptionTrial)
                    .filter(SubscriptionTrial.user_id == user.id)
                    .first()
                )
                if trial is None:
                    session.add(
                        SubscriptionTrial(
                            user_id=user.id,
                            trial_started_at=now,
                            trial_expires_at=trial_expires_at,
                            is_active=True,
                        )
                    )
                else:
                    trial.trial_started_at = now
                    trial.trial_expires_at = trial_expires_at
                    trial.is_active = True

                session.commit()
        finally:
            session.close()

    return jsonify({"status": "ok", "message": "kyc_verify_stub", "payload": payload})


@kyc_bp.get("/status")
def kyc_status():
    """Get KYC status.

    Expected query:
      - uid (or user_id): string/int

    Returns JSON:
      {"status": "verified|pending|rejected", "uid": <uid>}

    Note: Backend repo MVP does not include KYC status table yet.
    For now we map trial/premium/banned into a deterministic KYC status.
    """

    uid = request.args.get("uid") or request.args.get("user_id")
    if uid is None:
        return jsonify({"status": "error", "message": "missing_uid"}), 400

    try:
        uid_int = int(uid)
    except Exception:
        return jsonify({"status": "error", "message": "invalid_uid"}), 400

    from ..models import get_session
    from ..models.user import User
    from ..models.device_fingerprint import SubscriptionTrial

    now = dt.datetime.now(dt.timezone.utc)

    session = get_session()
    try:
        user = session.query(User).filter(User.id == uid_int).first()
        if user is None:
            return jsonify({"status": "error", "message": "user_not_found"}), 404

        is_blocked = bool(user.banned_until and user.banned_until > now)
        premium_active = bool(user.premium_until and user.premium_until > now)

        trial = session.query(SubscriptionTrial).filter(SubscriptionTrial.user_id == user.id).first()
        trial_active = bool(trial and trial.is_active and trial.trial_expires_at and trial.trial_expires_at > now)

        # Deterministic MVP mapping:
        # - blocked -> rejected
        # - premium_active or trial_active -> verified (best-effort)
        # - else -> pending
        if is_blocked:
            kyc_state = "rejected"
        elif premium_active or trial_active:
            kyc_state = "verified"
        else:
            kyc_state = "pending"

        return jsonify({"status": kyc_state, "uid": uid_int}), 200
    finally:
        session.close()

