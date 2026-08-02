from __future__ import annotations


def mock_location_heuristic(payload: dict | None) -> bool:
    """MVP heuristic.

    Client will send mock location signals from its own checks.
    Server also can maintain additional heuristics later.
    """
    payload = payload or {}
    # Common client signals
    if payload.get('mock_location_detected') is True:
        return True

    # Heuristic examples
    try:
        accuracy_m = float(payload.get('accuracy_m', 0.0) or 0.0)
        speed_kmh = float(payload.get('speed_kmh', 0.0) or 0.0)
    except Exception:
        return False

    if accuracy_m > 80:
        return True

    # unrealistic spikes stub
    if speed_kmh > 200:
        return True

    return False

