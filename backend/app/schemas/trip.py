"""Pydantic schemas for Trip."""

from datetime import datetime
from pydantic import BaseModel


class TripCreate(BaseModel):
    """Schema for starting a new trip."""
    vehicle_id: str
    start_latitude: float | None = None
    start_longitude: float | None = None


class TripResponse(BaseModel):
    """Schema for trip API responses."""
    id: str
    vehicle_id: str
    status: str
    start_time: datetime
    end_time: datetime | None = None
    start_latitude: float | None = None
    start_longitude: float | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None
    distance_km: float | None = None

    model_config = {"from_attributes": True}


class TripEnd(BaseModel):
    """Schema for ending a trip."""
    end_latitude: float | None = None
    end_longitude: float | None = None
