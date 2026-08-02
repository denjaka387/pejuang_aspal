from __future__ import annotations

"""REST rate limiting using flask-limiter.

MVP notes:
- Uses in-memory storage (memory://). Replace with Redis for production.
- Limits: 60 requests per minute per IP.
"""

from flask import Flask, request

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception as e:  # pragma: no cover
    # Keep app importable even if flask-limiter isn't installed yet.
    Limiter = None  # type: ignore
    get_remote_address = None  # type: ignore


def init_flask_limiter(app: Flask):
    if Limiter is None:
        # flask-limiter not installed; fail open for local dev.
        return None

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60/minute"],
        default_limits_per_method=False,
        storage_uri="memory://",
    )
    limiter.init_app(app)

    # Example: you can also set stricter limits per blueprint via decorators.
    return limiter


def get_client_ip() -> str:
    # Optional helper.
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")

