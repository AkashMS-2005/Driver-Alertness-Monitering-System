"""AI Connection State — in-memory model (not persisted to DB).

Tracks the live connection status between Laptop 2 and the AI service on Laptop 1.
"""

from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class AIConnectionState:
    """Transient state tracking AI service connectivity."""

    status: str = "DISCONNECTED"  # CONNECTED, DISCONNECTED, RECONNECTING
    last_detection_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    ai_server_host: str = ""
    ai_server_port: int = 8001
    reconnect_attempts: int = 0
    error_message: str | None = None

    @property
    def seconds_since_last_detection(self) -> float | None:
        """Seconds since the last AI detection was received."""
        if self.last_detection_at is None:
            return None
        return (datetime.now(timezone.utc) - self.last_detection_at).total_seconds()

    def mark_connected(self, host: str, port: int):
        """Mark the AI service as connected."""
        self.status = "CONNECTED"
        self.ai_server_host = host
        self.ai_server_port = port
        self.reconnect_attempts = 0
        self.error_message = None
        self.last_heartbeat_at = datetime.now(timezone.utc)

    def mark_disconnected(self, reason: str | None = None):
        """Mark the AI service as disconnected."""
        self.status = "DISCONNECTED"
        self.error_message = reason

    def mark_reconnecting(self):
        """Mark that a reconnection attempt is in progress."""
        self.status = "RECONNECTING"
        self.reconnect_attempts += 1

    def update_detection(self):
        """Update the last detection timestamp (called when an AI event is received)."""
        self.last_detection_at = datetime.now(timezone.utc)
        self.last_heartbeat_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Serialize to dictionary for API/WebSocket responses."""
        return {
            "status": self.status,
            "last_detection_at": (
                self.last_detection_at.isoformat() if self.last_detection_at else None
            ),
            "seconds_since_last_detection": self.seconds_since_last_detection,
            "ai_server_host": self.ai_server_host,
            "ai_server_port": self.ai_server_port,
            "reconnect_attempts": self.reconnect_attempts,
            "error_message": self.error_message,
        }
