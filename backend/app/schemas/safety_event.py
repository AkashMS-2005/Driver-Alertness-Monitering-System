"""Pydantic schemas for SafetyEvent."""

from datetime import datetime
from pydantic import BaseModel


class SafetyEventResponse(BaseModel):
    """Schema for safety event API responses — no raw CV metrics."""
    id: str
    trip_id: str
    vehicle_id: str
    event_type: str
    risk_level: str
    driver_status: str
    distraction_status: str
    description: str | None = None
    fatigue_level: int | None = None  # 0-100, smoothed human-meaningful value
    speed_kmh: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class SafetyStatusSnapshot(BaseModel):
    """Current safety status snapshot pushed via WebSocket — no raw CV metrics."""
    vehicle_id: str
    driver_status: str        # Alert, Drowsy, Fatigued, Distracted, Critical
    risk_level: str           # SAFE, WARNING, HIGH_RISK, CRITICAL
    safety_state: str         # Full state machine state
    fatigue_level: int        # 0-100 smoothed
    distraction_status: str   # Normal, Mild, Significant, Severe
    alert_message: str | None = None
    speed_kmh: float | None = None
    timestamp: datetime
