from __future__ import annotations

import datetime as dt

from flask import request
from flask_socketio import Namespace, emit, join_room, leave_room

from ..core.rate_limiter import RateLimiter
from ..models import get_session
from ..models.user import User
from ..services.moderation import moderate_message_or_raise



rate_limiter = RateLimiter()


class ChatNamespace(Namespace):
    """Namespace /chat: room chat, moderation anti-link."""

    def on_connect(self):
        emit("chat_connected", {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()})

    def on_join_room(self, data):
        room_id = (data or {}).get("room_id")
        if room_id:
            join_room(str(room_id))
            emit("joined_room", {"room_id": str(room_id)}, room=str(room_id))

    def on_leave_room(self, data):
        room_id = (data or {}).get("room_id")
        if room_id:
            leave_room(str(room_id))
            emit("left_room", {"room_id": str(room_id)}, room=str(room_id))

    def on_send_message(self, data):
        # Expected: { room_id, sender_id, message_text }
        if not isinstance(data, dict):
            return

        if not rate_limiter.allow(f"chat:{request.sid}"):
            emit("rate_limited", {"status": "error", "message": "Rate limited"})
            return

        room_id = data.get("room_id")
        sender_id = data.get("sender_id")
        message_text = (data.get("message_text") or "").strip()

        warning_text = "Peringatan: Dilarang mengirim tautan/link di room chat Pejuang Aspal!"

        if not room_id or sender_id is None:
            emit("link_blocked_warning", {"status": "error", "message": warning_text}, to=str(sender_id))
            return

        session = get_session()
        try:
            user = session.get(User, int(sender_id))
            if user is None:
                emit("chat_error", {"status": "error", "message": "user_not_found"}, to=str(request.sid))
                return

            now = dt.datetime.now(dt.timezone.utc)
            if user.banned_until and user.banned_until > now:
                emit("chat_error", {"status": "error", "message": "banned"}, to=str(request.sid))
                return

            try:
                moderate_message_or_raise(message_text)
            except ValueError:
                emit(
                    "link_blocked_warning",
                    {"status": "error", "message": warning_text},
                    to=str(sender_id),
                )
                return

            emit(
                "new_message",
                {"room_id": str(room_id), "sender_id": sender_id, "message_text": message_text, "t": now.isoformat()},
                room=str(room_id),
            )

        finally:
            session.close()


def register_chat_namespace(socketio):
    socketio.on_namespace(ChatNamespace("/chat"))

