from __future__ import annotations

from flask import Flask
from flask_socketio import SocketIO

from .core.config import Settings
from .core.security import init_security
from .models import init_db
from .sockets.radar import register_radar_namespace
from .sockets.chat import register_chat_namespace
from .sockets.test_connection import register_test_connection_namespace
from .sockets.lelang_socket import register_lelang_socket_namespace_test
from .sockets.sos_socket import register_sos_namespace
from .sockets.walkie_talkie_socket import register_walkie_talkie_namespace







def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings()

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.app_secret,
        DATABASE_URL=str(settings.database_url),
        SOCKET_CORS_ORIGINS=settings.socket_cors_origins,
    )

    init_security(app)
    init_db(app)

    # flask-socketio expects cors_allowed_origins either "*" or a list of origins.
    cors_allowed_origins = settings.socket_cors_origins

    socketio = SocketIO(
        app,
        cors_allowed_origins=cors_allowed_origins,
        async_mode="threading",  # MVP: keep simple; can switch to eventlet/gevent later
        ping_timeout=20,
        ping_interval=10,
    )

    register_radar_namespace(socketio)
    register_chat_namespace(socketio)
    register_test_connection_namespace(socketio)
    register_lelang_socket_namespace_test(socketio)
    register_sos_namespace(socketio)
    register_walkie_talkie_namespace(socketio)

    # Register REST APIs (MVP stubs)

    from .api.lelang import lelang_bp
    from .api.webhooks import webhooks_bp
    from .api.kyc import kyc_bp
    from .api.anti_fraud import anti_fraud_bp
    from .api.admin import admin_bp
    from .api.sos import sos_bp



    app.register_blueprint(lelang_bp, url_prefix="/api/lelang")
    app.register_blueprint(webhooks_bp, url_prefix="/api/webhooks")
    app.register_blueprint(kyc_bp, url_prefix="/api/kyc")
    app.register_blueprint(anti_fraud_bp, url_prefix="/api/anti-fraud")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(sos_bp, url_prefix="/api/sos")


    # store socketio for entrypoint
    app.extensions["socketio"] = socketio
    return app


def get_socketio(app: Flask) -> SocketIO:
    return app.extensions["socketio"]

