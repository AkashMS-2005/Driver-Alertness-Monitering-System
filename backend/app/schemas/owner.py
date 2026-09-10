"""Pydantic schemas for Owner."""

from datetime import datetime
from pydantic import BaseModel, EmailStr


class OwnerCreate(BaseModel):
    """Schema for creating a new owner."""
    name: str
    email: str
    phone: str | None = None
    password: str


class OwnerResponse(BaseModel):
    """Schema for owner API responses."""
    id: str
    name: str
    email: str
    phone: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OwnerLogin(BaseModel):
    """Schema for owner login."""
    email: str
    password: str


class OwnerTokenResponse(BaseModel):
    """Schema for login response with access token."""
    access_token: str
    token_type: str = "bearer"
    owner: OwnerResponse
