from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass

import socketio



@dataclass(frozen=True)
class Waypoint:
    lat: float
    lng: float


def interpolate(a: Waypoint, b: Waypoint, t: float) -> Waypoint:
    """Linear interpolation between two points."""
    return Waypoint(
        lat=a.lat + (b.lat - a.lat) * t,
        lng=a.lng + (b.lng - a.lng) * t,
    )


def build_route() -> list[Waypoint]:
    """Default route: a small loop around a road-area.

    You can replace with your real route points.
    """
    # Default values (example). Replace if needed.
    return [
        Waypoint(lat=-7.250445, lng=112.768845),
        Waypoint(lat=-7.251200, lng=112.770400),
        Waypoint(lat=-7.250900, lng=112.771500),
        Waypoint(lat=-7.250300, lng=112.770000),
    ]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GPS simulator for Radar namespace /radar")
    p.add_argument(
        "--server",
        default="http://10.15.210.139:5000",
        help="Socket.io server base URL (backend). Example: http://10.15.210.139:5000",
    )
    p.add_argument("--user-id", type=int, default=1, help="Driver user_id to emit")
    p.add_argument("--interval", type=float, default=1.5, help="Seconds between emits")

    p.add_argument(
        "--accuracy-m",
        type=float,
        default=10.0,
        help="accuracy_m payload (keep low to avoid mock GPS heuristic)",
    )
    p.add_argument("--speed-kmh", type=float, default=18.0, help="speed_kmh payload")

    p.add_argument(
        "--step",
        type=int,
        default=15,
        help="interpolation steps per segment (higher = smoother motion)",
    )

    p.add_argument(
        "--socketio-path",
        default="/socket.io",
        help="Socket.io path (default /socket.io). Only change if your server uses a different path.",
    )

    return p.parse_args()



def main() -> None:
    args = parse_args()
    route = build_route()

    radar_namespace = "/radar"

    # Controls whether we should send radar updates.
    # If backend is not ready or namespace isn't connected, we gate emits to prevent BadNamespaceError.
    radar_connected = threading.Event()

    # Socket.io client
    sio = socketio.Client(
        reconnection=True,
        reconnection_attempts=0,  # keep reconnecting forever
        reconnection_delay=2,
        reconnection_delay_max=5,
        logger=False,
        engineio_logger=False,
        # If your server uses long-polling only, force it via `transports=["polling"]`.
        # transports=["polling"],
    )

    # Global (engine) connect for debugging.
    @sio.event
    def connect():
        print("[gps_simulator_radar] connected to server (engine) " + args.server)

    @sio.event
    def connect_error(data):
        print("[gps_simulator_radar] connect_error (engine):", data)

    @sio.event
    def disconnect():
        radar_connected.clear()
        print("[gps_simulator_radar] disconnected from server (engine)")

    # Namespace handlers.
    @sio.on("connect", namespace=radar_namespace)
    def on_connect_radar():
        print(f"[gps_simulator_radar] connected to namespace {radar_namespace}")
        radar_connected.set()

    @sio.event(namespace=radar_namespace)
    def connect_error(data):
        # This callback is only best-effort; actual connect failures are also caught by the main connect().
        print(f"[gps_simulator_radar] connect_error (namespace {radar_namespace}):", data)
        radar_connected.clear()

    @sio.event(namespace=radar_namespace)
    def disconnect():
        radar_connected.clear()
        print(f"[gps_simulator_radar] disconnected from namespace {radar_namespace}")

    @sio.on("geofence_update", namespace=radar_namespace)
    def on_geofence_update(data):
        print("[gps_simulator_radar] geofence_update:", data)

    # Motion simulation (in a background thread, so the Socket.IO client event loop isn't blocked)
    stop_event = threading.Event()

    def emit_loop():
        segment_idx = 0
        while not stop_event.is_set():
            a = route[segment_idx % len(route)]
            b = route[(segment_idx + 1) % len(route)]

            for i in range(args.step):
                if stop_event.is_set():
                    break

                t = i / float(args.step - 1) if args.step > 1 else 1.0
                p = interpolate(a, b, t)

                payload = {
    "user_id": args.user_id,
    "lat": p.lat,
    "lng": p.lng,
    "accuracy_m": 10.0,       # <--- Kembalikan ke normal (di bawah 80 meter)
    "speed_kmh": 40.0,        # <--- Kembalikan ke normal (di bawah 180 km/h)
}

                # Gate emits: only send when /radar namespace is connected.
                # This prevents BadNamespaceError when backend/server is not ready yet.
                while not stop_event.is_set() and not radar_connected.is_set():
                    time.sleep(0.2)

                if stop_event.is_set():
                    break

                # namespace explicitly
                sio.emit("update_location", payload, namespace=radar_namespace)
                time.sleep(max(0.1, args.interval))

            segment_idx += 1

    emit_thread = threading.Thread(target=emit_loop, daemon=True)
    emit_thread.start()

    # Connect to server and request /radar namespace.
    # If server isn't ready, perform retry before emitting.
    max_namespace_retries = 30
    namespace_retry_delay = 1.0

    last_err: Exception | None = None
    for attempt in range(1, max_namespace_retries + 1):
        try:
            print(f"[gps_simulator_radar] connect attempt {attempt} to {args.server} (namespace {radar_namespace})")
            sio.connect(
                args.server,
                namespaces=[radar_namespace],
                socketio_path=args.socketio_path,
            )

            # Wait briefly for namespace to become connected.
            # If it times out, disconnect and retry.
            if radar_connected.wait(timeout=5.0):
                print(f"[gps_simulator_radar] /radar namespace is connected")
                break

            print(f"[gps_simulator_radar] namespace {radar_namespace} not connected yet; will retry")
            try:
                sio.disconnect()
            except Exception:
                pass

        except Exception as e:
            last_err = e
            print(f"[gps_simulator_radar] connect attempt {attempt} failed:", repr(e))
            try:
                sio.disconnect()
            except Exception:
                pass

        time.sleep(namespace_retry_delay)

    else:
        # If we cannot connect namespace after retries, keep the process alive so reconnection can happen.
        print(f"[gps_simulator_radar] WARNING: failed to connect namespace {radar_namespace} after retries")
        if last_err is not None:
            print("[gps_simulator_radar] last error:", repr(last_err))

    try:
        # Keep running and let the Socket.IO client handle incoming events.
        sio.wait()
    except KeyboardInterrupt:
        print("[gps_simulator_radar] stopped by user")
    finally:
        stop_event.set()
        try:
            sio.disconnect()
        except Exception:
            pass




if __name__ == "__main__":
    main()

