"""Test SMS integration: alert generation, inbound webhook, ACCEPT, REJECT, and history."""

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from app.db.database import init_db, async_session
from app.models.emergency_event import EmergencyEvent
from app.models.highway_assistance import HighwayAssistance
from app.models.vehicle import Vehicle
from app.models.trip import Trip
from app.models.owner import Owner
from app.models.emergency_sms_log import EmergencySmsLog
from app.services.sms_service import sms_service, _phone_numbers_match
from app.core.config import settings


async def run_tests():
    print("--- 1. Initializing DB ---")
    await init_db()

    async with async_session() as db:
        # Check or create default owner & vehicle & trip
        owner_res = await db.execute(select(Owner).limit(1))
        owner = owner_res.scalar_one_or_none()
        if not owner:
            owner = Owner(name="Test Owner", email="test@example.com", phone="+919876543210")
            db.add(owner)
            await db.flush()

        veh_res = await db.execute(select(Vehicle).limit(1))
        vehicle = veh_res.scalar_one_or_none()
        if not vehicle:
            vehicle = Vehicle(
                owner_id=owner.id,
                plate_number="KA-05-MJ-9999",
                make="Toyota",
                model="Camry",
                year=2024,
            )
            db.add(vehicle)
            await db.flush()

        trip_res = await db.execute(select(Trip).limit(1))
        trip = trip_res.scalar_one_or_none()
        if not trip:
            trip = Trip(
                vehicle_id=vehicle.id,
                driver_name="Test Driver",
                status="ACTIVE",
            )
            db.add(trip)
            await db.flush()

        # Create a test emergency
        now = datetime.now(timezone.utc)
        emergency = EmergencyEvent(
            trip_id=trip.id,
            vehicle_id=vehicle.id,
            owner_id=owner.id,
            emergency_type="AUTO_DROWSINESS",
            status="ACTIVE",
            trigger_source="AUTO_DROWSINESS",
            description="Test automatic emergency",
            latitude=12.9716,
            longitude=77.5946,
            place_name="Bengaluru",
            microsleep_count=2,
            drowsiness_percentage=85.0,
            detected_at=now,
            triggered_at=now,
        )
        db.add(emergency)
        await db.flush()

        assistance = HighwayAssistance(
            trip_id=trip.id,
            vehicle_id=vehicle.id,
            emergency_id=emergency.id,
            assistance_type="EMERGENCY_ASSISTANCE",
            assistance_name="Kengeri Toll Plaza (NICE Road)",
            status="REQUESTED",
            distance_km=14.0,
        )
        db.add(assistance)
        await db.commit()

        print(f"Created test emergency ID: {emergency.id}")
        short_id = emergency.id.replace("-", "")[-8:].upper()
        print(f"Short ID: #{short_id}")

    print("\n--- 2. Testing phone matching logic ---")
    assert _phone_numbers_match("+919876543210", "+919876543210")
    assert _phone_numbers_match("+91 98765 43210", "+91-9876543210")
    assert _phone_numbers_match("9876543210", "+919876543210")
    print("Phone matching: PASSED")

    print("\n--- 3. Testing SMS Alert Dispatch (Formatting & Storage) ---")
    settings.TOLL_ASSISTANCE_PHONE_NUMBER = "+919876543210"
    sms_log = await sms_service.send_emergency_alert(emergency.id)
    assert sms_log is not None
    print(f"SMS Log created: id={sms_log.id}, status={sms_log.sms_status}")
    print(f"SMS Body preview:\n{sms_log.sms_body}")
    assert f"#{short_id}" in sms_log.sms_body
    assert vehicle.plate_number in sms_log.sms_body
    assert "Kengeri Toll Plaza" in sms_log.sms_body
    print("SMS Alert Generation: PASSED")

    print("\n--- 4. Testing Inbound SMS: ACCEPT response ---")
    async with async_session() as db:
        success, reply_twiml, matched_em_id = await sms_service.handle_incoming_sms(
            from_number="+919876543210",
            body=f"ACCEPT {short_id}",
            message_sid="SM_TEST_ACCEPT_001",
            db=db,
        )
        print(f"Inbound ACCEPT result: success={success}, reply='{reply_twiml}'")
        assert success is True
        assert matched_em_id == emergency.id

        # Verify DB updated
        em_check = (await db.execute(select(EmergencyEvent).where(EmergencyEvent.id == emergency.id))).scalar_one()
        assert em_check.status == "ASSISTANCE_RESPONDED"
        assert em_check.response_message == "Highway assistance team has accepted the request."
        assert em_check.responded_at is not None
        print(f"DB Emergency status: {em_check.status}, responded_at: {em_check.responded_at}")

        # Verify SMS Log updated
        log_check_res = await db.execute(select(EmergencySmsLog).where(EmergencySmsLog.emergency_id == emergency.id).order_by(EmergencySmsLog.sent_at.desc()))
        logs = list(log_check_res.scalars().all())
        print(f"Found {len(logs)} logs for emergency {emergency.id}:")
        for l in logs:
            print(f"  Log ID: {l.id}, status: {l.sms_status}, assist_resp_status: {l.assistance_response_status}, phone: {l.assistance_phone_number}")
        assert any(l.assistance_response_status == "ACCEPTED" for l in logs)
        print("Inbound ACCEPT: PASSED")

    print("\n--- 5. Testing Inbound SMS: REJECT response ---")
    async with async_session() as db:
        # Create second emergency to test REJECT
        em2 = EmergencyEvent(
            trip_id=trip.id,
            vehicle_id=vehicle.id,
            owner_id=owner.id,
            emergency_type="AUTO_DROWSINESS",
            status="ACTIVE",
            trigger_source="AUTO_DROWSINESS",
            description="Second test emergency",
            latitude=12.9716,
            longitude=77.5946,
            microsleep_count=2,
            drowsiness_percentage=90.0,
            detected_at=datetime.now(timezone.utc),
        )
        db.add(em2)
        await db.commit()

        short_id2 = em2.id.replace("-", "")[-8:].upper()
        success, reply_twiml, matched_em_id = await sms_service.handle_incoming_sms(
            from_number="+919876543210",
            body=f"REJECT {short_id2}",
            message_sid="SM_TEST_REJECT_002",
            db=db,
        )
        print(f"Inbound REJECT result: success={success}, reply='{reply_twiml}'")
        assert success is True
        assert matched_em_id == em2.id

        em2_check = (await db.execute(select(EmergencyEvent).where(EmergencyEvent.id == em2.id))).scalar_one()
        assert em2_check.status == "ASSISTANCE_RESPONDED"
        assert em2_check.response_message == "Highway assistance rejected the request."
        print("Inbound REJECT: PASSED")

    print("\n--- 6. Testing Delivery Status Callback ---")
    async with async_session() as db:
        await sms_service.handle_delivery_status(
            message_sid=sms_log.sms_message_sid or "NONEXISTENT",
            message_status="delivered",
            db=db,
        )
        print("Delivery status callback test complete.")

    print("\nALL SMS INTEGRATION TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_tests())
