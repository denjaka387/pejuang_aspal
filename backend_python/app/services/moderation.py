from __future__ import annotations

import re

# Anti-Link: regex based (MVP)
# MVP regex: deteksi URL sederhana tanpa range karakter yang berpotensi error.
URL_REGEX = re.compile(
    r"(?i)(?:https?://)?(?:www\\.)?[A-Za-z0-9][A-Za-z0-9\\-]{0,200}\\.[A-Za-z]{2,63}(?:\\/\\S*)?"
)
DOMAIN_REGEX = re.compile(r"\b[A-Za-z0-9.-]+\.(?:[a-z]{2,63})\b", re.IGNORECASE)



def contains_link(message_text: str) -> bool:
    if not message_text:
        return False
    return bool(URL_REGEX.search(message_text) or DOMAIN_REGEX.search(message_text))


def moderate_message_or_raise(message_text: str) -> None:
    """Raise ValueError if message violates rules."""
    if contains_link(message_text):
        raise ValueError("link_detected")

