"""Verification script for Automatic Emergency Flow:
1. Normal -> Microsleep (continuous frames) -> count = 1, NO emergency.
2. Normal (recovery) -> Microsleep (2nd separate event) -> count = 2 -> AUTOMATIC EMERGENCY CREATED.
3. Highway assistance automatically requested & linked.
4. Owner WebSocket payload verified (EMERGENCY_TRIGGERED).
5. Emergency History persists in DB with microsleep_count >= 2.
6. Highway Assistance response recorded, verified in DB, and retained in History.
7. Reset verification: microsleep counter resets after assistance responds.
"""

import asyncio
import sys
import os

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import init_db, async_session
from app.main import seed_default_data
from app.risk_engine.emergency_engine import emergency_engine
from app.risk_engine.state_machine import risk_engine, update_active_vehicle_trip
from app.services.emergency_service import emergency_service
from app.models.emergency_event import EmergencyEvent
from app.models.highway_assistance import HighwayAssistance
from app.websocket.connection_manager import manager
from sqlalchemy import select, update
from datetime import datetime, timezone


async def run_verification():
    print("=" * 70)
    print("SMARTDRIVE GUARDIAN — AUTOMATIC EMERGENCY SYSTEM VERIFICATION")
    print("=" * 70)

    # 1. Init DB & seed
    await init_db()
    await seed_default_data()

    # Clean up prior test runs
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        await db.execute(
            update(EmergencyEvent)
            .where(EmergencyEvent.status.in_(["ACTIVE", "DRIVER_RECOVERED"]))
            .values(status="RESOLVED", resolved_at=now)
        )
        await db.commit()

    # Reset emergency engine to clean state
    emergency_engine.reset_for_new_trip()
    print("[INIT] Database initialized, seed checked, engine reset.")

    # Intercept WebSocket broadcasts for verification
    broadcasted_messages = []
    original_broadcast = manager.broadcast_to_all
    async def mock_broadcast(msg):
        broadcasted_messages.append(msg)
        await original_broadcast(msg)
    manager.broadcast_to_all = mock_broadcast

    # -------------------------------------------------------------------------
    # TEST 1 & 2: Continuous microsleep frames -> edge detection must count as 1
    # -------------------------------------------------------------------------
    print("\n--- TEST 1 & 2: First Microsleep Event (Edge Detection) ---")
    vehicle_id, trip_id = await risk_engine._resolve_vehicle_trip_ids()

    # Frame 1: MICROSLEEP
    await emergency_engine.on_ai_event("MICROSLEEP", drowsiness_percentage=82.0, vehicle_id=vehicle_id, trip_id=trip_id)
    # Frame 2-5: Continuous MICROSLEEP frames
    for _ in range(4):
        await emergency_engine.on_ai_event("MICROSLEEP", drowsiness_percentage=85.0, vehicle_id=vehicle_id, trip_id=trip_id)

    print(f"Microsleep count after continuous frames: {emergency_engine.microsleep_count} (Expected: 1)")
    assert emergency_engine.microsleep_count == 1, f"Expected 1, got {emergency_engine.microsleep_count}"
    assert not emergency_engine.has_active_emergency, "No emergency should be created after 1 microsleep"
    print("PASS: 1 continuous microsleep counted as ONE event, NO emergency created.")

    # -------------------------------------------------------------------------
    # TEST 3 & 4: Recovery -> 2nd Separate Microsleep -> AUTOMATIC EMERGENCY
    # -------------------------------------------------------------------------
    print("\n--- TEST 3 & 4: Recovery followed by 2nd Separate Microsleep ---")
    # Driver recovers to NORMAL
    await emergency_engine.on_ai_event("NORMAL", drowsiness_percentage=20.0, vehicle_id=vehicle_id, trip_id=trip_id)
    assert emergency_engine.microsleep_count == 1, "Count should remain 1 during normal driving"

    # Second separate MICROSLEEP event begins
    await emergency_engine.on_ai_event("MICROSLEEP", drowsiness_percentage=88.5, vehicle_id=vehicle_id, trip_id=trip_id)
    print(f"Microsleep count after second separate event: {emergency_engine.microsleep_count} (Expected: 2)")
    assert emergency_engine.microsleep_count == 2, f"Expected 2, got {emergency_engine.microsleep_count}"

    # Wait for the async _fire_emergency task to complete
    await asyncio.sleep(0.5)

    assert emergency_engine.has_active_emergency, "Active emergency MUST be set after 2nd microsleep"
    emergency_id = emergency_engine.active_emergency_id
    assert emergency_id is not None, "Emergency ID must not be None"
    print(f"PASS: Automatic emergency successfully fired! Emergency ID = {emergency_id}")

    # -------------------------------------------------------------------------
    # TEST 5: Verify HighwayAssistance created & Owner WebSocket broadcast
    # -------------------------------------------------------------------------
    print("\n--- TEST 5: Verify Highway Assistance & Owner WebSocket ---")
    async with async_session() as db:
        em_res = await db.execute(select(EmergencyEvent).where(EmergencyEvent.id == emergency_id))
        emergency = em_res.scalar_one_or_none()
        assert emergency is not None, "Emergency record must exist in DB"
        assert emergency.microsleep_count == 2, f"Expected microsleep_count 2, got {emergency.microsleep_count}"
        assert emergency.status == "ACTIVE", f"Expected ACTIVE status, got {emergency.status}"

        assist_res = await db.execute(select(HighwayAssistance).where(HighwayAssistance.emergency_id == emergency_id))
        assist = assist_res.scalar_one_or_none()
        assert assist is not None, "HighwayAssistance record must be created and linked to emergency"
        assert assist.status == "REQUESTED", f"Assistance status should be REQUESTED, got {assist.status}"
        print(f"DB Emergency Record: status={emergency.status}, microsleeps={emergency.microsleep_count}, place={emergency.place_name}")
        print(f"DB Assistance Record: name={assist.assistance_name}, distance={assist.distance_km}km, status={assist.status}")

    # Verify Owner WebSocket broadcast
    triggered_broadcasts = [m for m in broadcasted_messages if m.get("type") == "EMERGENCY_TRIGGERED"]
    assert len(triggered_broadcasts) >= 1, "EMERGENCY_TRIGGERED broadcast must be sent over WebSocket"
    payload = triggered_broadcasts[0]
    assert payload["emergency_id"] == emergency_id
    assert payload["microsleep_count"] == 2
    assert payload["status"] == "ACTIVE"
    print(f"PASS: Owner WebSocket received EMERGENCY_TRIGGERED: assistance={payload.get('assistance_name')}, distance={payload.get('assistance_distance_km')}km")

    # -------------------------------------------------------------------------
    # TEST 6: Emergency History persistence
    # -------------------------------------------------------------------------
    print("\n--- TEST 6: Emergency History Query ---")
    async with async_session() as db:
        history = await emergency_service.get_emergency_history(vehicle_id, db)
        assert len(history) > 0, "History must contain at least 1 emergency"
        latest = history[0]
        assert latest.id == emergency_id
        assert latest.microsleep_count >= 2
        print(f"PASS: Emergency History retrieved from DB: ID={latest.id}, microsleeps={latest.microsleep_count}, status={latest.status}")

    # -------------------------------------------------------------------------
    # TEST 7 & 8: Assistance response
    # -------------------------------------------------------------------------
    print("\n--- TEST 7 & 8: Highway Assistance Response ---")
    response_msg = "Highway assistance team dispatched from Nelamangala Toll Plaza. ETA 8 minutes."
    async with async_session() as db:
        updated_em = await emergency_service.respond_to_emergency(emergency_id, response_msg, db)
        await db.commit()

    assert updated_em.status == "ASSISTANCE_RESPONDED"
    assert updated_em.response_message == response_msg
    assert updated_em.responded_at is not None

    # Check WebSocket broadcast for response
    resp_broadcasts = [m for m in broadcasted_messages if m.get("type") == "ASSISTANCE_RESPONSE"]
    assert len(resp_broadcasts) >= 1, "ASSISTANCE_RESPONSE broadcast must be sent over WebSocket"
    assert resp_broadcasts[0]["message"] == response_msg
    print(f"PASS: Assistance response recorded and broadcasted: '{response_msg}'")

    # Verify history still contains the record with the response
    async with async_session() as db:
        history_after = await emergency_service.get_emergency_history(vehicle_id, db)
        latest_after = history_after[0]
        assert latest_after.id == emergency_id
        assert latest_after.status == "ASSISTANCE_RESPONDED"
        assert latest_after.response_message == response_msg
        print(f"PASS: Emergency remains in DB History with status='ASSISTANCE_RESPONDED' and response message preserved.")

    # -------------------------------------------------------------------------
    # TEST 9: Reset verification
    # -------------------------------------------------------------------------
    print("\n--- TEST 9: Counter Reset After Response ---")
    print(f"Microsleep count after assistance response: {emergency_engine.microsleep_count} (Expected: 0)")
    assert emergency_engine.microsleep_count == 0, f"Expected 0, got {emergency_engine.microsleep_count}"
    print("PASS: Microsleep counter reset to 0 for next driving episode.")

    print("\n" + "=" * 70)
    print("ALL 10 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_verification())
