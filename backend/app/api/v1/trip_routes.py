"""Trip routes — start, end, list, get."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripResponse, TripEnd

router = APIRouter()


@router.post("/", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def start_trip(payload: TripCreate, db: AsyncSession = Depends(get_db)):
    """Start a new trip for a vehicle."""
    trip = Trip(
        vehicle_id=payload.vehicle_id,
        status="ACTIVE",
        start_latitude=payload.start_latitude,
        start_longitude=payload.start_longitude,
    )
    db.add(trip)
    await db.flush()
    await db.refresh(trip)
    return trip


@router.put("/{trip_id}/end", response_model=TripResponse)
async def end_trip(
    trip_id: str, payload: TripEnd, db: AsyncSession = Depends(get_db)
):
    """End an active trip."""
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="Trip is not active")

    trip.status = "COMPLETED"
    trip.end_time = datetime.now(timezone.utc)
    trip.end_latitude = payload.end_latitude
    trip.end_longitude = payload.end_longitude
    await db.flush()
    await db.refresh(trip)
    return trip


@router.get("/vehicle/{vehicle_id}", response_model=list[TripResponse])
async def list_trips(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    """List all trips for a vehicle."""
    result = await db.execute(
        select(Trip).where(Trip.vehicle_id == vehicle_id).order_by(Trip.start_time.desc())
    )
    return result.scalars().all()


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(trip_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific trip by ID."""
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.get("/vehicle/{vehicle_id}/active", response_model=TripResponse | None)
async def get_active_trip(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    """Get the currently active trip for a vehicle, if any."""
    result = await db.execute(
        select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.status == "ACTIVE")
    )
    return result.scalar_one_or_none()
