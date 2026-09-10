"""Vehicle routes — register, list, get."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleResponse

router = APIRouter()


@router.post(
    "/{owner_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_vehicle(
    owner_id: str, payload: VehicleCreate, db: AsyncSession = Depends(get_db)
):
    """Register a new vehicle for an owner."""
    # Check for duplicate plate
    result = await db.execute(
        select(Vehicle).where(Vehicle.plate_number == payload.plate_number)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Plate number already registered")

    vehicle = Vehicle(
        owner_id=owner_id,
        plate_number=payload.plate_number,
        make=payload.make,
        model=payload.model,
        year=payload.year,
    )
    db.add(vehicle)
    await db.flush()
    await db.refresh(vehicle)
    return vehicle


@router.get("/{owner_id}", response_model=list[VehicleResponse])
async def list_vehicles(owner_id: str, db: AsyncSession = Depends(get_db)):
    """List all vehicles for an owner."""
    result = await db.execute(select(Vehicle).where(Vehicle.owner_id == owner_id))
    return result.scalars().all()


@router.get("/detail/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific vehicle by ID."""
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle
