"""Emergency event routes."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.db.database import get_db
from app.models.emergency_event import EmergencyEvent

router = APIRouter()


class EmergencyCreate(BaseModel):
    trip_id: str
    vehicle_id: str
    emergency_type: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class EmergencyResponse(BaseModel):
    id: str
    trip_id: str
    vehicle_id: str
    emergency_type: str
    status: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    detected_at: datetime
    resolved_at: datetime | None = None
    model_config = {"from_attributes": True}


@router.post("/", response_model=EmergencyResponse, status_code=status.HTTP_201_CREATED)
async def create_emergency(
    payload: EmergencyCreate, db: AsyncSession = Depends(get_db)
):
    """Record a new emergency event."""
    event = EmergencyEvent(
        trip_id=payload.trip_id,
        vehicle_id=payload.vehicle_id,
        emergency_type=payload.emergency_type,
        description=payload.description,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


@router.put("/{emergency_id}/resolve")
async def resolve_emergency(
    emergency_id: str, new_status: str = "RESOLVED", db: AsyncSession = Depends(get_db)
):
    """Resolve an emergency event."""
    result = await db.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Emergency event not found")

    event.status = new_status
    event.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "resolved", "new_status": new_status}


@router.get("/vehicle/{vehicle_id}", response_model=list[EmergencyResponse])
async def list_emergencies_for_vehicle(
    vehicle_id: str, db: AsyncSession = Depends(get_db)
):
    """List emergency events for a vehicle."""
    result = await db.execute(
        select(EmergencyEvent)
        .where(EmergencyEvent.vehicle_id == vehicle_id)
        .order_by(EmergencyEvent.detected_at.desc())
    )
    return result.scalars().all()
