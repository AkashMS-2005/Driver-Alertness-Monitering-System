"""Dashboard aggregation endpoint — single call returns everything the unified frontend needs.

GET /api/v1/dashboard/state
  Returns:
    - Current drowsiness state + perclos (live from AI client cache)
    - Active trip info
    - Latest vehicle location
    - Recent safety events (last 10)
    - Owner + vehicle metadata
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import get_db
from app.models.vehicle import Vehicle
from app.models.owner import Owner
from app.models.trip import Trip
from app.models.location import Location
from app.models.safety_event import SafetyEvent
from app.ai_client.ai_ws_client import ai_ws_client
from app.risk_engine.state_machine import risk_engine

logger = logging.getLogger("smartdrive")
router = APIRouter()


@router.get("/state")
async def get_dashboard_state(db: AsyncSession = Depends(get_db)):
    """Return a single aggregated snapshot for the unified dashboard.

    Combines:
      - Live drowsiness state (AI client cache)
      - Active trip
      - Latest location
      - Recent safety events
      - Vehicle + owner info
    """
    # --- Vehicle & Owner ---
    veh_result = await db.execute(select(Vehicle).limit(1))
    vehicle = veh_result.scalar_one_or_none()

    owner = None
    if vehicle:
        owner_result = await db.execute(select(Owner).where(Owner.id == vehicle.owner_id))
        owner = owner_result.scalar_one_or_none()

    # --- Active Trip ---
    active_trip = None
    trip_duration_seconds = 0
    if vehicle:
        trip_result = await db.execute(
            select(Trip)
            .where(Trip.vehicle_id == vehicle.id, Trip.status == "ACTIVE")
            .limit(1)
        )
        active_trip = trip_result.scalar_one_or_none()
        if active_trip:
            delta = datetime.now(timezone.utc) - active_trip.start_time.replace(
                tzinfo=timezone.utc
            ) if active_trip.start_time.tzinfo is None else datetime.now(timezone.utc) - active_trip.start_time
            trip_duration_seconds = int(delta.total_seconds())

    # --- Latest Location ---
    latest_location = None
    if vehicle:
        loc_result = await db.execute(
            select(Location)
            .where(Location.vehicle_id == vehicle.id)
            .order_by(Location.timestamp.desc())
            .limit(1)
        )
        latest_location = loc_result.scalar_one_or_none()

    # --- Recent Safety Events ---
    recent_db_events = []
    if vehicle:
        ev_result = await db.execute(
            select(SafetyEvent)
            .where(SafetyEvent.vehicle_id == vehicle.id)
            .order_by(SafetyEvent.timestamp.desc())
            .limit(10)
        )
        recent_db_events = ev_result.scalars().all()

    # Merge in-memory events from risk engine (newest first)
    in_mem_events = risk_engine.get_recent_events(limit=10)

    # Build combined event list (prefer in-memory for most recent, db for history)
    combined_events = []
    for e in in_mem_events:
        combined_events.append({
            "timestamp": e.get("timestamp"),
            "state": e.get("state"),
            "risk_level": e.get("risk_level"),
            "description": e.get("description"),
        })
    for e in recent_db_events:
        combined_events.append({
            "timestamp": e.timestamp.isoformat(),
            "state": e.driver_status.upper(),
            "risk_level": e.risk_level,
            "description": e.description,
        })
    # Keep latest 10 unique (by timestamp)
    seen = set()
    deduped = []
    for e in combined_events:
        key = e.get("timestamp", "")
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    combined_events = deduped[:10]

    # --- Drowsiness State ---
    live = ai_ws_client.latest_drowsiness or {}
    current_state = live.get("state") or risk_engine.current_state
    perclos = float(live.get("perclos", 0.0))
    risk_level = live.get("risk_level") or (
        "HIGH" if current_state == "MICROSLEEP"
        else "MEDIUM" if current_state == "DROWSY"
        else "LOW"
    )

    return {
        "drowsiness": {
            "state": current_state,
            "risk_level": risk_level,
            "perclos": round(perclos, 1),
            "ear": float(live.get("ear", 0.0)),
            "eye_closed": bool(live.get("eye_closed", False)),
            "yawning": bool(live.get("yawning", False)),
            "alert_message": live.get("alert_message", "Driver Alert"),
            "timestamp": live.get("timestamp"),
        },
        "vehicle": {
            "id": vehicle.id if vehicle else None,
            "plate_number": vehicle.plate_number if vehicle else "N/A",
            "make": vehicle.make if vehicle else "N/A",
            "model": vehicle.model if vehicle else "N/A",
            "year": vehicle.year if vehicle else None,
        },
        "owner": {
            "id": owner.id if owner else None,
            "name": owner.name if owner else "N/A",
            "email": owner.email if owner else "N/A",
            "phone": owner.phone if owner else None,
        },
        "trip": {
            "id": active_trip.id if active_trip else None,
            "status": active_trip.status if active_trip else "NO_ACTIVE_TRIP",
            "start_time": active_trip.start_time.isoformat() if active_trip else None,
            "duration_seconds": trip_duration_seconds,
            "distance_km": float(active_trip.distance_km or 0.0) if active_trip else 0.0,
            "start_latitude": active_trip.start_latitude if active_trip else None,
            "start_longitude": active_trip.start_longitude if active_trip else None,
        },
        "location": {
            "latitude": latest_location.latitude if latest_location else None,
            "longitude": latest_location.longitude if latest_location else None,
            "speed_kmh": float(latest_location.speed_kmh) if latest_location else 0.0,
            "timestamp": latest_location.timestamp.isoformat() if latest_location else None,
            "gps_available": latest_location is not None,
        },
        "safety_events": combined_events,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
