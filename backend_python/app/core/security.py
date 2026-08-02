from __future__ import annotations

from flask import Flask


def init_security(app: Flask) -> None:
    # Placeholder for future anti-tamper checks, E2E key exchange bootstrap, etc.
    # For MVP, we only ensure Flask has security-related defaults.
    app.config.setdefault("JSON_SORT_KEYS", False)



