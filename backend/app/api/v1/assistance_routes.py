"""Highway assistance routes."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.db.database import get_db
from app.models.highway_assistance import HighwayAssistance

router = APIRouter()


class AssistanceRequest(BaseModel):
    trip_id: str
    vehicle_id: str
    assistance_type: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class AssistanceResponse(BaseModel):
    id: str
    trip_id: str
    vehicle_id: str
    assistance_type: str
    status: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    requested_at: datetime
    resolved_at: datetime | None = None
    model_config = {"from_attributes": True}


@router.post("/", response_model=AssistanceResponse, status_code=status.HTTP_201_CREATED)
async def request_assistance(
    payload: AssistanceRequest, db: AsyncSession = Depends(get_db)
):
    """Request highway assistance."""
    assistance = HighwayAssistance(
        trip_id=payload.trip_id,
        vehicle_id=payload.vehicle_id,
        assistance_type=payload.assistance_type,
        description=payload.description,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    db.add(assistance)
    await db.flush()
    await db.refresh(assistance)
    return assistance


@router.put("/{assistance_id}/status")
async def update_assistance_status(
    assistance_id: str, new_status: str, db: AsyncSession = Depends(get_db)
):
    """Update the status of an assistance request."""
    result = await db.execute(
        select(HighwayAssistance).where(HighwayAssistance.id == assistance_id)
    )
    assistance = result.scalar_one_or_none()
    if not assistance:
        raise HTTPException(status_code=404, detail="Assistance request not found")

    assistance.status = new_status
    if new_status in ("COMPLETED", "CANCELLED"):
        assistance.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "updated", "new_status": new_status}


@router.get("/vehicle/{vehicle_id}", response_model=list[AssistanceResponse])
async def list_assistance_for_vehicle(
    vehicle_id: str, db: AsyncSession = Depends(get_db)
):
    """List assistance requests for a vehicle."""
    result = await db.execute(
        select(HighwayAssistance)
        .where(HighwayAssistance.vehicle_id == vehicle_id)
        .order_by(HighwayAssistance.requested_at.desc())
    )
    return result.scalars().all()
