from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Any

# Ensure `backend_python/` is on sys.path when this file is executed as a script.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)


from flask import Flask, request
from flask_socketio import SocketIO


# REST Rate Limiting (flask-limiter)
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:  # pragma: no cover
    Limiter = None  # type: ignore
    get_remote_address = None  # type: ignore

# SocketIO async_mode stability
# NOTE: On Windows, eventlet/gevent can cause socket binding issues (WinError 10048).
# Force stable mode for local development.

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pejuang_aspal_secret_key'


if Limiter is not None and get_remote_address is not None:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["120/minute"],
        default_limits_per_method=False,
        storage_uri="memory://",
    )
    limiter.init_app(app)
else:
    limiter = None

# NOTE: On Windows, force a stable thread-based server to avoid WinError 10048.
async_mode = 'threading'


socketio = SocketIO(
    app,
    cors_allowed_origins='*',
    async_mode=async_mode,
    ping_interval=25,
    ping_timeout=60,
    logger=False,
    engineio_logger=False,
)


# Radar namespace registration
# Namespace handler ada di `backend_python/app/sockets/radar.py` supaya event names & payload
# konsisten untuk semua client (Flutter & simulator).
try:
    # When running this file as a script, `app` is importable from backend_python/app.
    from app.sockets.radar import register_radar_namespace

    register_radar_namespace(socketio)
except Exception as e:  # pragma: no cover
    print('[backend] WARNING: failed to register Radar namespace /radar:', repr(e))


# SOS REST API Blueprint (menggantikan Cloud Functions untuk FCM push notification)
try:
    from app.api.sos import sos_bp

    app.register_blueprint(sos_bp, url_prefix='/api/sos')
except Exception as e:  # pragma: no cover
    print('[backend] WARNING: failed to register SOS API blueprint:', repr(e))





from flask import jsonify


@app.post('/api/radar/location')
def post_radar_location():
    """Receive real GPS update from frontend.

    Expected JSON payload:
    - user_id: int
    - lat: float
    - lng: float
    - accuracy_m: float (meters)
    - speed_kmh: float
    - bearing: optional
    """

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    session = None
    try:
        from app.models import get_session

        session = get_session()
        # Shared logic + fraud checks
        from app.sockets.radar import process_radar_location_update

        result = process_radar_location_update(
            data=data,
            session=session,
            emit_geofence=True,
            fraud_emit=True,
        )

        if not result.get('ok'):
            # Emit fraud_detected when available
            fraud_payload = result.get('fraud_payload')
            if fraud_payload:
                socketio.emit('fraud_detected', fraud_payload, namespace='/radar')

            return jsonify({'status': 'error', 'message': result.get('error_message') or 'invalid_payload'}), 400

        geofence_payload = result.get('geofence_payload')
        if geofence_payload:
            socketio.emit('geofence_update', geofence_payload, namespace='/radar')

        return jsonify({'status': 'ok', 'geofence_update': geofence_payload}), 200

    finally:
        try:
            if session is not None:
                session.close()
        except Exception:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))

    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
