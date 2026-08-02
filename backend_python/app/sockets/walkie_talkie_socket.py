from __future__ import annotations

import datetime as dt
import base64

from flask import request
from flask_socketio import Namespace, emit, join_room, leave_room

from ..core.rate_limiter import RateLimiter

rate_limiter = RateLimiter()


class WalkieTalkieNamespace(Namespace):
    """Namespace /walkie: full-duplex audio relay for walkie-talkie.

    Events:
        - client -> server:
            * join_channel   { channel_id, user_id, display_name }
            * leave_channel  { channel_id, user_id }
            * audio_data     { channel_id, data (base64 chunk), sequence }
            * audio_end      { channel_id, user_id }
        - server -> client:
            * walkie_connected
            * walkie_error   { status, message }
            * audio_data     { from_user_id, from_name, channel_id, data, sequence }
            * audio_end      { from_user_id, channel_id }
    """

    def on_connect(self):
        emit(
            "walkie_connected",
            {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()},
        )

    def on_ping(self, data):
        if not rate_limiter.allow(f"walkie:ping:{getattr(request, 'sid', 'unknown')}"):
            emit("walkie_error", {"status": "error", "message": "rate_limited"})
            return

        emit(
            "walkie_pong",
            {"status": "ok", "t": dt.datetime.now(dt.timezone.utc).isoformat()},
            namespace="/walkie",
        )

    def on_join_channel(self, data):
        """Join a socket.io room named by channel_id.
        The client must call this after connecting to start receiving audio.
        """
        channel_id = data.get("channel_id")
        user_id = data.get("user_id")
        display_name = data.get("display_name", f"Driver #{user_id}")

        if not channel_id or not user_id:
            emit("walkie_error", {"status": "error", "message": "missing channel_id or user_id"})
            return

        join_room(channel_id)
        # Store user info on the socket for later use
        request.user_data = {
            "user_id": user_id,
            "display_name": display_name,
            "channel_id": channel_id,
        }

        emit("walkie_joined", {
            "status": "ok",
            "channel_id": channel_id,
            "user_id": user_id,
            "t": dt.datetime.now(dt.timezone.utc).isoformat(),
        }, room=request.sid)

        print(f"[Walkie] User {display_name} (ID={user_id}) joined channel {channel_id}")

    def on_leave_channel(self, data):
        """Leave a socket.io room."""
        channel_id = data.get("channel_id")
        user_id = data.get("user_id")

        if not channel_id:
            return

        leave_room(channel_id)
        request.user_data = None

        print(f"[Walkie] User (ID={user_id}) left channel {channel_id}")

    def on_audio_data(self, data):
        """Receive an audio chunk from a speaker and broadcast to all
        OTHER members in the same channel room (excluding sender).
        """
        channel_id = data.get("channel_id")
        audio_chunk = data.get("data")  # base64-encoded PCM/Opus chunk
        sequence = data.get("sequence", 0)
        user_id = data.get("user_id")
        display_name = data.get("display_name", f"Driver #{user_id}")

        if not channel_id or not audio_chunk or user_id is None:
            emit("walkie_error", {"status": "error", "message": "invalid audio_data payload"})
            return

        # Broadcast to everyone in the channel EXCEPT the sender
        emit("audio_data", {
            "from_user_id": user_id,
            "from_name": display_name,
            "channel_id": channel_id,
            "data": audio_chunk,
            "sequence": sequence,
        }, room=channel_id, include_self=False)

    def on_audio_end(self, data):
        """Signal that the speaker has stopped transmitting."""
        channel_id = data.get("channel_id")
        user_id = data.get("user_id")

        if not channel_id or user_id is None:
            return

        # Notify all OTHER members that audio transmission has ended
        emit("audio_end", {
            "from_user_id": user_id,
            "channel_id": channel_id,
        }, room=channel_id, include_self=False)

        print(f"[Walkie] User ID={user_id} stopped talking on channel {channel_id}")

    def on_disconnect(self):
        """Handle user disconnect — optionally clean up."""
        sid = getattr(request, "sid", "unknown")
        print(f"[Walkie] Client disconnected: {sid}")


def register_walkie_talkie_namespace(socketio) -> None:
    socketio.on_namespace(WalkieTalkieNamespace("/walkie"))

