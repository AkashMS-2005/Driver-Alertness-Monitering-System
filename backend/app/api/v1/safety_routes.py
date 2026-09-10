"""Safety routes — list safety events and statistics for owner dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.database import get_db
from app.models.safety_event import SafetyEvent
from app.schemas.safety_event import SafetyEventResponse
from app.risk_engine.state_machine import risk_engine
from app.ai_client.ai_ws_client import ai_ws_client

router = APIRouter()


@router.get("/events", response_model=list[SafetyEventResponse])
async def list_all_safety_events(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List recent safety events across all vehicles."""
    result = await db.execute(
        select(SafetyEvent)
        .order_by(SafetyEvent.timestamp.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return events


@router.get("/stats")
async def get_safety_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate statistics for the owner dashboard."""
    drowsy_count_res = await db.execute(
        select(func.count(SafetyEvent.id)).where(SafetyEvent.event_type.like("%DROWSY%"))
    )
    microsleep_count_res = await db.execute(
        select(func.count(SafetyEvent.id)).where(SafetyEvent.event_type.like("%MICROSLEEP%"))
    )
    total_events_res = await db.execute(select(func.count(SafetyEvent.id)))

    drowsy_count = drowsy_count_res.scalar() or 0
    microsleep_count = microsleep_count_res.scalar() or 0
    total_events = total_events_res.scalar() or 0

    # Also count in-memory recent events if DB was just initialized
    in_mem_events = risk_engine.get_recent_events(limit=20)
    for evt in in_mem_events:
        if evt.get("state") == "DROWSY" and drowsy_count == 0:
            drowsy_count += 1
        elif evt.get("state") == "MICROSLEEP" and microsleep_count == 0:
            microsleep_count += 1

    latest_perclos = 0.0
    if ai_ws_client.latest_drowsiness:
        latest_perclos = float(ai_ws_client.latest_drowsiness.get("perclos", 0.0))

    return {
        "current_state": risk_engine.current_state,
        "current_risk": "HIGH" if risk_engine.current_state == "MICROSLEEP" else "MEDIUM" if risk_engine.current_state == "DROWSY" else "LOW",
        "drowsy_events_count": drowsy_count,
        "microsleep_events_count": microsleep_count,
        "total_events_count": max(total_events, len(in_mem_events)),
        "latest_perclos": latest_perclos,
    }


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
