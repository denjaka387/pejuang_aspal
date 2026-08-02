from __future__ import annotations

import datetime as dt

from . import kyc_bp  # noqa: F401


def _coerce_bool(val):
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "y", "verified"}
    return False

