from __future__ import annotations

import hashlib

def normalize_fingerprint(value: str) -> str:
    return (value or '').strip()


def fingerprint_hash(value: str) -> str:
    """Deterministic hash of fingerprint string (MVP)."""
    v = normalize_fingerprint(value)
    if not v:
        raise ValueError('fingerprint_empty')
    return hashlib.sha256(v.encode('utf-8')).hexdigest()

