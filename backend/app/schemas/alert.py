"""Pydantic schemas for Alert."""

from datetime import datetime
from pydantic import BaseModel


class AlertResponse(BaseModel):
    """Schema for alert API responses."""
    id: str
    vehicle_id: str
    owner_id: str
    alert_type: str
    severity: str
    message: str
    acknowledged: bool
    timestamp: datetime

    model_config = {"from_attributes": True}


class AlertAcknowledge(BaseModel):
    """Schema for acknowledging an alert."""
    acknowledged: bool = True
