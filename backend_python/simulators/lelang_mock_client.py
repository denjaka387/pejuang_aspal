from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from typing import Any, Optional

import socketio


# NOTE:
# Backend expects payload on namespace /test.
# Event: on_driver_take_order
# Encrypted format:
#   {
#     "enc": { "nonce": "<b64>", "ciphertext": "<b64>", "tag": "<b64>" },
#     "aad": "optional"  // optional AAD string
#   }
# Decryption uses AES-256-GCM with key bytes decoded from LELANG_E2E_KEY_B64.
#
# This script implements two scenarios:
#   - payload_ok: encrypt with valid backend key
#   - payload_bad: use wrong key OR tamper ciphertext to break auth tag


def _b64_to_key32(key_b64: str) -> bytes:
    key_bytes = base64.b64decode(key_b64, validate=True)
    if len(key_bytes) != 32:
        raise ValueError("LELANG_E2E_KEY_B64 must decode to 32 bytes (AES-256)")
    return key_bytes


def _encrypt_aes_256_gcm(payload_obj: dict[str, Any], key_32: bytes, *, aad: Optional[bytes] = None) -> dict[str, Any]:
    """Mirror backend/app/core/e2e_crypto.py envelope format."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aesgcm = AESGCM(key_32)
    aad_bytes = aad if aad is not None else None

    plaintext = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ct_and_tag = aesgcm.encrypt(nonce=nonce, data=plaintext, associated_data=aad_bytes)

    tag_len = 16
    ciphertext = ct_and_tag[:-tag_len]
    tag = ct_and_tag[-tag_len:]

    return {
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def build_envelope_for_driver_take_order(*, order_id: int, driver_user_id: int, key_32: bytes, aad_str: Optional[str]) -> dict[str, Any]:
    body = {"order_id": int(order_id), "driver_user_id": int(driver_user_id)}
    aad_bytes = aad_str.encode("utf-8") if aad_str is not None else None
    enc = _encrypt_aes_256_gcm(body, key_32, aad=aad_bytes)

    envelope: dict[str, Any] = {"enc": enc}
    if aad_str is not None:
        envelope["aad"] = aad_str
    return envelope


def tamper_envelope_ciphertext(wrapper: dict[str, Any]) -> dict[str, Any]:
    """Tamper ciphertext but keep base64 decodable => auth tag mismatch."""
    enc = dict(wrapper["enc"])
    ct = base64.b64decode(enc["ciphertext"], validate=True)
    # flip one bit in ciphertext
    if len(ct) == 0:
        raise ValueError("ciphertext empty")
    ct_arr = bytearray(ct)
    ct_arr[0] ^= 0x01
    enc["ciphertext"] = base64.b64encode(bytes(ct_arr)).decode("ascii")

    out = dict(wrapper)
    out["enc"] = enc
    return out


def tamper_envelope_wrong_tag_or_nonce(wrapper: dict[str, Any]) -> dict[str, Any]:
    """Alternative tamper: flip one bit in tag."""
    enc = dict(wrapper["enc"])
    tag = base64.b64decode(enc["tag"], validate=True)
    if len(tag) == 0:
        raise ValueError("tag empty")
    tag_arr = bytearray(tag)
    tag_arr[-1] ^= 0x01
    enc["tag"] = base64.b64encode(bytes(tag_arr)).decode("ascii")

    out = dict(wrapper)
    out["enc"] = enc
    return out


def run(namespace: str, backend_url: str, order_id: int, driver_user_id: int, scenario: str, *, aad: Optional[str], tamper_mode: str) -> int:
    # Client
    sio = socketio.Client(logger=False, engineio_logger=False)

    done = False
    status_events: list[tuple[str, Any]] = []

    @sio.event(namespace=namespace)
    def connect():
        print(f"[client] Connected to {backend_url} namespace={namespace}")

    @sio.on("lelang_socket_connected", namespace=namespace)
    def on_connected(data):
        print(f"[client] lelang_socket_connected: {data}")

    @sio.on("order_dimenangkan", namespace=namespace)
    def on_winner(data):
        nonlocal done
        print(f"[client] order_dimenangkan: {data}")
        status_events.append(("order_dimenangkan", data))
        done = True

    @sio.on("order_take_rejected", namespace=namespace)
    def on_rejected(data):
        nonlocal done
        print(f"[client] order_take_rejected: {data}")
        status_events.append(("order_take_rejected", data))
        done = True

    @sio.on("security_error", namespace=namespace)
    def on_security_error(data):
        nonlocal done
        print(f"[client] security_error: {data}")
        status_events.append(("security_error", data))
        # backend also emits order_take_rejected for crypto issues
        done = True

    @sio.on("order_sudah_diambil", namespace=namespace)
    def on_taken_broadcast(data):
        print(f"[client] order_sudah_diambil (broadcast): {data}")

    def resolve_key_bytes() -> tuple[bytes, bytes]:
        key_b64 = os.getenv("LELANG_E2E_KEY_B64")
        if not key_b64:
            raise RuntimeError("Missing env var LELANG_E2E_KEY_B64")
        valid_key = _b64_to_key32(key_b64)

        # wrong key: flip one byte deterministically
        wrong_key = bytearray(valid_key)
        wrong_key[0] ^= 0x55
        return bytes(valid_key), bytes(wrong_key)

    valid_key, wrong_key = resolve_key_bytes()

    if scenario == "payload_ok":
        envelope = build_envelope_for_driver_take_order(
            order_id=order_id,
            driver_user_id=driver_user_id,
            key_32=valid_key,
            aad_str=aad,
        )

    elif scenario == "payload_bad":
        # Option 1: wrong key
        envelope = build_envelope_for_driver_take_order(
            order_id=order_id,
            driver_user_id=driver_user_id,
            key_32=wrong_key,
            aad_str=aad,
        )

        # Option 2/3: additionally tamper ciphertext/tag so failure is guaranteed
        if tamper_mode == "ciphertext":
            envelope = tamper_envelope_ciphertext(envelope)
        elif tamper_mode == "tag":
            envelope = tamper_envelope_wrong_tag_or_nonce(envelope)
        elif tamper_mode == "none":
            pass
        else:
            raise ValueError("tamper_mode must be one of: ciphertext|tag|none")

    else:
        raise ValueError("scenario must be payload_ok or payload_bad")

    # Connect + emit
    print(f"[client] Connecting... scenario={scenario} order_id={order_id} driver_user_id={driver_user_id}")

    sio.connect(backend_url, namespaces=[namespace], transports=["websocket"])

    # Emit
    payload = envelope
    print(f"[client] Emitting on_driver_take_order with payload keys={list(payload.keys())}")
    sio.emit("on_driver_take_order", payload, namespace=namespace)

    # Wait for result
    t0 = time.time()
    while time.time() - t0 < 10:
        if done:
            break
        time.sleep(0.2)

    sio.disconnect()

    # Best-effort exit code: verify expected event.
    expected = "order_dimenangkan" if scenario == "payload_ok" else "security_error"
    got_types = {k for k, _ in status_events}
    if scenario == "payload_ok":
        return 0 if "order_dimenangkan" in got_types else 2
    return 0 if "security_error" in got_types or "order_take_rejected" in got_types else 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default=os.getenv("SOCKETIO_BACKEND_URL", "http://localhost:5000"))
    parser.add_argument("--namespace", default="/test")
    parser.add_argument("--order-id", type=int, required=True)
    parser.add_argument("--driver-user-id", type=int, required=True)
    parser.add_argument("--scenario", choices=["payload_ok", "payload_bad"], required=True)
    parser.add_argument("--aad", default=None, help="Optional AAD string (must match what frontend uses)")
    parser.add_argument("--tamper-mode", choices=["ciphertext", "tag", "none"], default="ciphertext")

    args = parser.parse_args()

    try:
        rc = run(
            namespace=args.namespace,
            backend_url=args.backend_url,
            order_id=args.order_id,
            driver_user_id=args.driver_user_id,
            scenario=args.scenario,
            aad=args.aad,
            tamper_mode=args.tamper_mode,
        )
    except Exception as e:
        print(f"[client] ERROR: {e}", file=sys.stderr)
        return 1

    print(f"[client] done rc={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

