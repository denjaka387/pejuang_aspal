from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceIntegritySignals:
    # MVP flags; in production you will map from platform-specific attestation APIs.
    is_rooted: bool = False
    app_tampered: bool = False
    mock_location_detected: bool = False


def validate_device_integrity(signals: dict | None) -> DeviceIntegritySignals:
    signals = signals or {}
    return DeviceIntegritySignals(
        is_rooted=bool(signals.get('is_rooted', False)),
        app_tampered=bool(signals.get('app_tampered', False)),
        mock_location_detected=bool(signals.get('mock_location_detected', False)),
    )


def integrity_is_blocked(s: DeviceIntegritySignals) -> bool:
    # MVP rule: if rooted or tampered or mock location.
    return bool(s.is_rooted or s.app_tampered or s.mock_location_detected)

