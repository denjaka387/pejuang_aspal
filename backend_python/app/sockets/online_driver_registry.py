from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class DriverLocation:
    lat: float
    lng: float
    updated_at_iso: str
    app_ecosystem: str



class OnlineDriverRegistry:
    """In-memory registry for latest driver location.

    NOTE: MVP (no persistence). Reset on server restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._driver_locations: Dict[int, DriverLocation] = {}

    def set_location(
        self,
        driver_user_id: int,
        lat: float,
        lng: float,
        updated_at_iso: str,
        app_ecosystem: str,
    ) -> None:
        with self._lock:
            self._driver_locations[int(driver_user_id)] = DriverLocation(
                lat=float(lat),
                lng=float(lng),
                updated_at_iso=updated_at_iso,
                app_ecosystem=app_ecosystem or "",
            )


    def get_location(self, driver_user_id: int) -> Optional[DriverLocation]:
        with self._lock:
            return self._driver_locations.get(int(driver_user_id))

    def get_all_locations(self) -> Dict[int, DriverLocation]:
        with self._lock:
            return dict(self._driver_locations)


# Singleton (imported by socket namespaces)
online_driver_registry = OnlineDriverRegistry()

