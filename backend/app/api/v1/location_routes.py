"""Location routes — GPS position storage and retrieval.

Supports:
  POST /api/v1/locations/              — store a GPS fix for a vehicle/trip
  GET  /api/v1/locations/vehicle/{id}/latest   — latest location for a vehicle
  GET  /api/v1/locations/trip/{trip_id}        — full history for a trip
  POST /api/v1/locations/demo          — update the demo vehicle's location (dev helper)
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.db.database import get_db
from app.models.location import Location

router = APIRouter()


# ---------- Pydantic schemas ----------

class LocationCreate(BaseModel):
    vehicle_id: str
    trip_id: str | None = None
    latitude: float
    longitude: float
    speed_kmh: float = 0.0
    heading: float | None = None


class LocationResponse(BaseModel):
    id: str
    vehicle_id: str
    trip_id: str | None = None
    latitude: float
    longitude: float
    speed_kmh: float
    heading: float | None = None
    timestamp: datetime
    model_config = {"from_attributes": True}


# ---------- Endpoints ----------

@router.post("/", response_model=LocationResponse, status_code=201)
async def store_location(payload: LocationCreate, db: AsyncSession = Depends(get_db)):
    """Store a new GPS position for a vehicle.

    Call this whenever a real GPS fix is received.
    For development without hardware, use the /demo helper endpoint.
    """
    loc = Location(
        vehicle_id=payload.vehicle_id,
        trip_id=payload.trip_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed_kmh=payload.speed_kmh,
        heading=payload.heading,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(loc)
    await db.flush()
    await db.refresh(loc)
    return loc


@router.get("/vehicle/{vehicle_id}/latest", response_model=LocationResponse | None)
async def get_latest_location(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    """Get the most recent GPS fix for a vehicle.

    Returns null if no location data has been stored yet.
    """
    result = await db.execute(
        select(Location)
        .where(Location.vehicle_id == vehicle_id)
        .order_by(Location.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/trip/{trip_id}", response_model=list[LocationResponse])
async def get_trip_locations(
    trip_id: str,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """Get location history for a trip (ordered oldest → newest for map rendering)."""
    result = await db.execute(
        select(Location)
        .where(Location.trip_id == trip_id)
        .order_by(Location.timestamp.asc())
        .limit(limit)
    )
    return result.scalars().all()


class DemoLocationUpdate(BaseModel):
    latitude: float
    longitude: float
    speed_kmh: float = 60.0


@router.post("/demo", response_model=LocationResponse)
async def update_demo_location(
    payload: DemoLocationUpdate, db: AsyncSession = Depends(get_db)
):
    """[DEV] Push a GPS fix for the default demo vehicle.

    Use this endpoint during development when no real GPS hardware is connected.
    """
    from app.db.database import async_session as _make_session
    from app.models.vehicle import Vehicle
    from app.models.trip import Trip

    # Find the default vehicle
    veh_result = await db.execute(select(Vehicle).limit(1))
    vehicle = veh_result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="No vehicle registered in the system yet")

    # Find active trip
    trip_result = await db.execute(
        select(Trip)
        .where(Trip.vehicle_id == vehicle.id, Trip.status == "ACTIVE")
        .limit(1)
    )
    trip = trip_result.scalar_one_or_none()

    loc = Location(
        vehicle_id=vehicle.id,
        trip_id=trip.id if trip else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        speed_kmh=payload.speed_kmh,
        heading=None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(loc)
    await db.flush()
    await db.refresh(loc)
    return loc
