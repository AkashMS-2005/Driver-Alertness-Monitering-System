"""Pydantic schemas for AI connection status."""

from datetime import datetime
from pydantic import BaseModel


class AIConnectionResponse(BaseModel):
    """Schema for AI connection status API response."""
    status: str                              # CONNECTED, DISCONNECTED, RECONNECTING
    last_detection_at: datetime | None = None
    seconds_since_last_detection: float | None = None
    ai_server_host: str = ""
    ai_server_port: int = 8001
    reconnect_attempts: int = 0
    error_message: str | None = None


class AIConnectionWSEvent(BaseModel):
    """WebSocket event pushed when AI connection status changes."""
    event_type: str = "AI_CONNECTION_STATUS_UPDATE"
    status: str
    last_detection_at: datetime | None = None
    seconds_since_last_detection: float | None = None
    message: str  # Human-readable, e.g. "AI CAMERA: CONNECTED"
