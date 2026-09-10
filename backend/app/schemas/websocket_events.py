"""Pydantic schemas for WebSocket event payloads."""

from datetime import datetime
from pydantic import BaseModel
from typing import Any


class WebSocketMessage(BaseModel):
    """Base schema for all WebSocket messages sent to dashboards."""
    event_type: str
    timestamp: datetime
    data: dict[str, Any]


class SafetyStatusUpdate(BaseModel):
    """SAFETY_STATUS_UPDATE event payload — human-readable only."""
    event_type: str = "SAFETY_STATUS_UPDATE"
    vehicle_id: str
    driver_status: str        # Alert, Drowsy, Fatigued, Distracted, Critical, Unknown
    risk_level: str           # SAFE, WARNING, HIGH_RISK, CRITICAL
    safety_state: str         # Full state machine state
    fatigue_level: int        # 0-100 smoothed indicator
    distraction_status: str   # Normal, Mild, Significant, Severe
    alert_message: str | None = None
    speed_kmh: float | None = None
    timestamp: datetime


class LocationUpdate(BaseModel):
    """LOCATION_UPDATE event payload."""
    event_type: str = "LOCATION_UPDATE"
    vehicle_id: str
    latitude: float
    longitude: float
    speed_kmh: float
    heading: float | None = None
    timestamp: datetime


class TripUpdate(BaseModel):
    """TRIP_UPDATE event payload."""
    event_type: str = "TRIP_UPDATE"
    trip_id: str
    vehicle_id: str
    status: str
    start_time: datetime
    end_time: datetime | None = None
    timestamp: datetime


class AlertEvent(BaseModel):
    """ALERT_NEW event payload."""
    event_type: str = "ALERT_NEW"
    alert_id: str
    vehicle_id: str
    alert_type: str
    severity: str
    message: str
    timestamp: datetime


class AssistanceUpdate(BaseModel):
    """ASSISTANCE_UPDATE event payload."""
    event_type: str = "ASSISTANCE_UPDATE"
    assistance_id: str
    vehicle_id: str
    assistance_type: str
    status: str
    timestamp: datetime


class EmergencyUpdate(BaseModel):
    """EMERGENCY_UPDATE event payload."""
    event_type: str = "EMERGENCY_UPDATE"
    emergency_id: str
    vehicle_id: str
    emergency_type: str
    status: str
    description: str | None = None
    timestamp: datetime
