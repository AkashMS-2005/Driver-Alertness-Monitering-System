"""Pydantic schemas for Vehicle."""

from datetime import datetime
from pydantic import BaseModel


class VehicleCreate(BaseModel):
    """Schema for registering a new vehicle."""
    plate_number: str
    make: str
    model: str
    year: int


class VehicleResponse(BaseModel):
    """Schema for vehicle API responses."""
    id: str
    owner_id: str
    plate_number: str
    make: str
    model: str
    year: int
    created_at: datetime

    model_config = {"from_attributes": True}


class VehicleUpdate(BaseModel):
    """Schema for updating vehicle details."""
    plate_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
