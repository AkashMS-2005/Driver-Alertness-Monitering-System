"""Safety routes — list safety events for a trip or vehicle."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.safety_event import SafetyEvent
from app.schemas.safety_event import SafetyEventResponse

router = APIRouter()


@router.get("/trip/{trip_id}", response_model=list[SafetyEventResponse])
async def list_safety_events_for_trip(
    trip_id: str, db: AsyncSession = Depends(get_db)
):
    """List all safety events for a specific trip."""
    result = await db.execute(
        select(SafetyEvent)
        .where(SafetyEvent.trip_id == trip_id)
        .order_by(SafetyEvent.timestamp.desc())
    )
    return result.scalars().all()


@router.get("/vehicle/{vehicle_id}", response_model=list[SafetyEventResponse])
async def list_safety_events_for_vehicle(
    vehicle_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List recent safety events for a vehicle."""
    result = await db.execute(
        select(SafetyEvent)
        .where(SafetyEvent.vehicle_id == vehicle_id)
        .order_by(SafetyEvent.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()
