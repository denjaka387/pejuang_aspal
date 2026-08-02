from __future__ import annotations

import datetime as dt

from flask import request
from flask_socketio import Namespace, emit


class TestConnectionNamespace(Namespace):
    """Namespace /test: lightweight ping for verifying socket connectivity."""

    def on_connect(self):
        emit(
            "test_connection",
            {
                "status": "connected",
                "t": dt.datetime.now(dt.timezone.utc).isoformat(),
                "sid": request.sid,
            },
        )

    def on_test_connection(self, data):
        # Client may send {"message": "..."}
        message = ""
        if isinstance(data, dict):
            message = str(data.get("message", ""))

        emit(
            "test_connection",
            {
                "status": "ok",
                "echo": message,
                "t": dt.datetime.now(dt.timezone.utc).isoformat(),
                "sid": request.sid,
            },
        )


def register_test_connection_namespace(socketio) -> None:
    socketio.on_namespace(TestConnectionNamespace("/test"))

