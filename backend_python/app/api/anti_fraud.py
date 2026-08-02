from __future__ import annotations

import datetime as dt

from flask import Blueprint, jsonify, request

from ..core.rate_limiter import RateLimiter
from ..models import get_session
from ..models.user import User
from ..models.device_fingerprint import DeviceFingerprint, SubscriptionTrial
from ..services.fingerprint import fingerprint_hash
from ..services.device_integrity import integrity_is_blocked, validate_device_integrity

from ..services.mock_location import mock_location_heuristic

anti_fraud_bp = Blueprint('anti_fraud', __name__)
rate_limiter = RateLimiter()


def _trial_active(user: User) -> tuple[bool, dt.datetime | None]:
    now = dt.datetime.now(dt.timezone.utc)
    trial = None
    session = get_session()
    try:
        trial = session.query(SubscriptionTrial).filter(SubscriptionTrial.user_id == user.id).first()
    finally:
        session.close()

    if trial is None:
        return False, None

    # If server says active but expired, treat as inactive.
    if not trial.is_active:
        return False, trial.trial_expires_at

    if trial.trial_expires_at and trial.trial_expires_at > now:
        return True, trial.trial_expires_at

    return False, trial.trial_expires_at


@anti_fraud_bp.post('/register-device')
def register_device():
    """Register unique device fingerprint.

    Body (MVP):
    - user_id: int
    - fingerprint: str
    - integrity_signals: { is_rooted, app_tampered, mock_location_detected }
    - mock_location_signals: { ... } (optional)
    """

    payload = request.get_json(silent=True) or {}
    user_id = payload.get('user_id')
    fingerprint = payload.get('fingerprint')
    integrity_signals = payload.get('integrity_signals')
    mock_location_signals = payload.get('mock_location_signals')

    if user_id is None or fingerprint is None:
        return jsonify({'status': 'error', 'message': 'missing_user_id_or_fingerprint'}), 400

    if not rate_limiter.allow(f'anti_fraud:register_device:{user_id}', capacity=10, refill_per_sec=1.0):
        return jsonify({'status': 'error', 'message': 'rate_limited'}), 429

    session = get_session()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            return jsonify({'status': 'error', 'message': 'user_not_found'}), 404

        f_hash = fingerprint_hash(str(fingerprint))

        device_row = session.query(DeviceFingerprint).filter(DeviceFingerprint.fingerprint_hash == f_hash).first()
        if device_row is not None:
            # If fingerprint already exists, enforce permanent ownership.
            if int(device_row.user_id) != int(user.id):
                return jsonify({'status': 'error', 'message': 'Perangkat ini sudah terdaftar pada akun lain'}), 409

            # Idempotent: fingerprint belongs to the same user.
            return jsonify({'status': 'ok', 'message': 'already_registered', 'blocked': False}), 200


        integrity: DeviceIntegritySignals = validate_device_integrity(integrity_signals)

        is_mock = mock_location_heuristic(mock_location_signals)
        is_blocked = integrity_is_blocked(integrity) or is_mock

        device_row = DeviceFingerprint(
            fingerprint_hash=f_hash,
            user_id=user.id,
            is_rooted=integrity.is_rooted,
            app_tampered=integrity.app_tampered,
            mock_location_detected=(integrity.mock_location_detected or is_mock),
        )

        session.add(device_row)

        # If blocked/integrity fail, ban user temporarily (MVP).
        if is_blocked:
            now = dt.datetime.now(dt.timezone.utc)
            user.mock_location_detected = True
            user.banned_until = now + dt.timedelta(days=30)
            user.banned_reason = 'anti_fraud_device_integrity_stub'
            user.is_active = False

        session.commit()

        return jsonify({'status': 'ok', 'message': 'device_registered', 'blocked': is_blocked}), 201
    finally:
        session.close()


@anti_fraud_bp.post('/kyc-success')
def kyc_success():
    """Bind/validate device fingerprint after KYC success.

    Body (MVP):
    - user_id: int
    - fingerprint_hash: str (hashed on client)
    """

    payload = request.get_json(silent=True) or {}
    user_id = payload.get('user_id')
    fingerprint_hash_value = payload.get('fingerprint_hash')

    if user_id is None:
        return jsonify({'status': 'error', 'message': 'missing_user_id'}), 400


    if fingerprint_hash_value is None:
        return jsonify({'status': 'error', 'message': 'missing_fingerprint_hash'}), 400

    if not rate_limiter.allow(f'anti_fraud:kyc_success:{user_id}', capacity=10, refill_per_sec=1.0):
        return jsonify({'status': 'error', 'message': 'rate_limited'}), 429


    session = get_session()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            return jsonify({'status': 'error', 'message': 'user_not_found'}), 404

        now = dt.datetime.now(dt.timezone.utc)
        if user.banned_until and user.banned_until > now:
            return jsonify({'status': 'error', 'message': 'user_blocked'}), 403

        trial = session.query(SubscriptionTrial).filter(SubscriptionTrial.user_id == user.id).first()
        if trial is not None and trial.is_active and trial.trial_expires_at and trial.trial_expires_at > now:
            return jsonify({'status': 'ok', 'message': 'trial_already_active', 'trial_expires_at': trial.trial_expires_at.isoformat()})

        trial_started_at = now
        trial_expires_at = now + dt.timedelta(days=30)

        if trial is None:
            trial = SubscriptionTrial(
                user_id=user.id,
                trial_started_at=trial_started_at,
                trial_expires_at=trial_expires_at,
                is_active=True,
            )
            session.add(trial)
        else:
            trial.trial_started_at = trial_started_at
            trial.trial_expires_at = trial_expires_at
            trial.is_active = True

        session.commit()

        # Synchronize fingerprint binding with KYC (hashed fingerprint from client).
        device_row = (
            session.query(DeviceFingerprint)
            .filter(DeviceFingerprint.fingerprint_hash == fingerprint_hash_value)
            .first()
        )

        if device_row is None:
            return jsonify({'status': 'error', 'message': 'Perangkat belum terdaftar'}), 409

        if int(device_row.user_id) != int(user.id):
            return jsonify({'status': 'error', 'message': 'Perangkat ini sudah terdaftar pada akun lain'}), 409

        return jsonify({'status': 'ok', 'message': 'trial_started', 'trial_expires_at': trial_expires_at.isoformat()})

    finally:
        session.close()


@anti_fraud_bp.get('/status')
def status():
    """Get trial/premium/banned status.

    Query (MVP):
    - user_id: int
    """

    user_id = request.args.get('user_id', type=int)
    if user_id is None:
        return jsonify({'status': 'error', 'message': 'missing_user_id'}), 400

    session = get_session()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            return jsonify({'status': 'error', 'message': 'user_not_found'}), 404

        now = dt.datetime.now(dt.timezone.utc)
        is_blocked = bool(user.banned_until and user.banned_until > now)

        # Premium
        premium_active = bool(user.premium_until and user.premium_until > now)

        # Trial
        trial = session.query(SubscriptionTrial).filter(SubscriptionTrial.user_id == user.id).first()
        trial_active = bool(trial and trial.is_active and trial.trial_expires_at and trial.trial_expires_at > now)

        return jsonify(
            {
                'status': 'ok',
                'is_blocked': is_blocked,
                'banned_until': user.banned_until.isoformat() if user.banned_until else None,
                'banned_reason': user.banned_reason,
                'premium_active': premium_active,
                'premium_until': user.premium_until.isoformat() if user.premium_until else None,
                'trial_active': trial_active,
                'trial_expires_at': trial.trial_expires_at.isoformat() if trial else None,
                'trial_message': 'Masa Trial Habis' if trial and trial.trial_expires_at and trial.trial_expires_at <= now else None,
            }
        )
    finally:
        session.close()

