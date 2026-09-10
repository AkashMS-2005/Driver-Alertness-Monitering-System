"""AI connection service — manages connection state and pushes updates."""

import logging
from datetime import datetime, timezone
from app.models.ai_connection_state import AIConnectionState
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")


class AIConnectionService:
    """Manages the AI connection state and broadcasts changes to dashboards."""

    def __init__(self):
        self.state = AIConnectionState()

    async def on_connected(self, host: str, port: int):
        """Called when AI service connection is established."""
        self.state.mark_connected(host, port)
        logger.info(f"AI CONNECTION: CONNECTED — {host}:{port}")
        await self._broadcast_status()

    async def on_disconnected(self, reason: str | None = None):
        """Called when AI service connection is lost."""
        self.state.mark_disconnected(reason)
        logger.warning(f"AI CONNECTION: DISCONNECTED — {reason}")
        await self._broadcast_status()

    async def on_reconnecting(self):
        """Called when a reconnection attempt starts."""
        self.state.mark_reconnecting()
        logger.info(
            f"AI CONNECTION: RECONNECTING — attempt #{self.state.reconnect_attempts}"
        )
        await self._broadcast_status()

    async def on_detection_received(self):
        """Called each time an AI detection event arrives."""
        self.state.update_detection()

    async def _broadcast_status(self):
        """Push AI_CONNECTION_STATUS_UPDATE to all connected dashboards."""
        seconds_ago = self.state.seconds_since_last_detection
        if self.state.status == "CONNECTED":
            message = "AI CAMERA: CONNECTED"
        elif self.state.status == "RECONNECTING":
            message = "AI CAMERA: RECONNECTING..."
        else:
            if seconds_ago is not None:
                message = (
                    f"Driver monitoring connection lost. "
                    f"Last detection received {int(seconds_ago)}s ago."
                )
            else:
                message = "Driver monitoring unavailable."

        payload = {
            "event_type": "AI_CONNECTION_STATUS_UPDATE",
            "status": self.state.status,
            "last_detection_at": (
                self.state.last_detection_at.isoformat()
                if self.state.last_detection_at
                else None
            ),
            "seconds_since_last_detection": seconds_ago,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.broadcast_to_all(payload)

    def get_state(self) -> AIConnectionState:
        """Return the current connection state object."""
        return self.state


# Singleton
ai_connection_service = AIConnectionService()
