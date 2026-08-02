from __future__ import annotations

from flask import Blueprint, jsonify, request


webhooks_bp = Blueprint("webhooks", __name__)


@webhooks_bp.post("/midtrans/premium")
def midtrans_premium_webhook():
    # MVP stub: verify signature + mark premium_until.
    payload = request.get_json(silent=True) or {}
    return jsonify({"status": "ok", "message": "midtrans_webhook_stub", "payload": payload})

