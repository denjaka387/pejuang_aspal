from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class E2ECryptoError(ValueError):
    """Raised when encryption/decryption fails (auth tag mismatch, bad base64, etc.)."""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(s: str) -> bytes:
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # pragma: no cover
        raise E2ECryptoError("invalid_base64") from e


def _ensure_32byte_key(key_32: bytes) -> None:
    if not isinstance(key_32, (bytes, bytearray)):
        raise E2ECryptoError("key_not_bytes")
    if len(key_32) != 32:
        raise E2ECryptoError("invalid_key_length_not_32")


def encrypt_aes_256_gcm(plaintext: bytes, key_32: bytes, aad: bytes | None = None, *, nonce_len: int = 12) -> dict[str, Any]:
    """Encrypt plaintext using AES-256-GCM.

    Envelope output:
      {
        "nonce": "<b64>",
        "ciphertext": "<b64>",
        "tag": "<b64>"
      }

    Notes:
    - AESGCM in cryptography appends the 128-bit tag to the ciphertext.
    - We split it out explicitly so client/server can send/receive `tag` separately.
    """
    _ensure_32byte_key(key_32)

    if not isinstance(plaintext, (bytes, bytearray)):
        raise E2ECryptoError("plaintext_not_bytes")

    if aad is not None and not isinstance(aad, (bytes, bytearray)):
        raise E2ECryptoError("aad_not_bytes")

    if nonce_len <= 0:
        raise E2ECryptoError("invalid_nonce_len")

    nonce = AESGCM.generate_key(bit_length=256)  # dummy to keep mypy quiet
    # Actual nonce generation
    import os

    nonce = os.urandom(nonce_len)

    aesgcm = AESGCM(bytes(key_32))
    aad_bytes = bytes(aad) if aad is not None else None

    ct_and_tag = aesgcm.encrypt(nonce=nonce, data=bytes(plaintext), associated_data=aad_bytes)

    # cryptography AESGCM returns ciphertext || tag
    # Tag length for GCM is 16 bytes (128-bit)
    tag_len = 16
    if len(ct_and_tag) < tag_len:
        raise E2ECryptoError("ciphertext_too_short")

    ciphertext = ct_and_tag[:-tag_len]
    tag = ct_and_tag[-tag_len:]

    return {
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
        "tag": _b64e(tag),
    }


def decrypt_aes_256_gcm(envelope: dict[str, Any], key_32: bytes, aad: bytes | None = None) -> bytes:
    """Decrypt AES-256-GCM envelope.

    Expected envelope shape:
      {
        "nonce": "<b64>",
        "ciphertext": "<b64>",
        "tag": "<b64>"
      }

    Raises:
      - E2ECryptoError on auth/tag mismatch, invalid base64, or malformed envelope.
    """
    _ensure_32byte_key(key_32)

    if not isinstance(envelope, dict):
        raise E2ECryptoError("envelope_not_dict")

    try:
        nonce_b64 = envelope["nonce"]
        ciphertext_b64 = envelope["ciphertext"]
        tag_b64 = envelope["tag"]
    except KeyError as e:
        raise E2ECryptoError(f"missing_envelope_field_{e.args[0]}") from e

    if not isinstance(nonce_b64, str) or not isinstance(ciphertext_b64, str) or not isinstance(tag_b64, str):
        raise E2ECryptoError("envelope_fields_not_str")

    nonce = _b64d(nonce_b64)
    ciphertext = _b64d(ciphertext_b64)
    tag = _b64d(tag_b64)

    if len(tag) != 16:
        raise E2ECryptoError("invalid_tag_len")

    aesgcm = AESGCM(bytes(key_32))
    aad_bytes = bytes(aad) if aad is not None else None

    ct_and_tag = ciphertext + tag
    try:
        return aesgcm.decrypt(nonce=nonce, data=ct_and_tag, associated_data=aad_bytes)
    except Exception as e:
        # includes InvalidTag
        raise E2ECryptoError("decrypt_failed_invalid_tag_or_key") from e


def decrypt_envelope_json(
    wrapper: dict[str, Any],
    key_32: bytes,
    *,
    aad: bytes | None = None,
) -> Any:
    """Convenience: decrypt wrapper -> JSON payload.

    wrapper expected to be:
      { "enc": {nonce,ciphertext,tag}, "aad": <optional str> }

    Returns parsed JSON.
    """

    if not isinstance(wrapper, dict):
        raise E2ECryptoError("wrapper_not_dict")

    enc = wrapper.get("enc")
    if not isinstance(enc, dict):
        raise E2ECryptoError("wrapper_missing_enc")

    # If wrapper contains its own AAD field, prefer it.
    aad_field = wrapper.get("aad")
    effective_aad = aad
    if aad_field is not None:
        if not isinstance(aad_field, str):
            raise E2ECryptoError("aad_field_not_str")
        effective_aad = aad_field.encode("utf-8")

    plaintext_bytes = decrypt_aes_256_gcm(enc, key_32=key_32, aad=effective_aad)
    try:
        return json.loads(plaintext_bytes.decode("utf-8"))
    except Exception as e:
        raise E2ECryptoError("plaintext_not_valid_json") from e

