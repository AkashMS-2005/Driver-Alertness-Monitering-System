"""SMS Service — handles outbound alerts and inbound replies with Twilio."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import async_session
from app.models.emergency_event import EmergencyEvent
from app.models.highway_assistance import HighwayAssistance
from app.models.vehicle import Vehicle
from app.models.emergency_sms_log import EmergencySmsLog
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")


def _normalize_phone(num: str | None) -> str:
    """Normalize phone number to digits only (strip spaces, +, -, (, ))."""
    if not num:
        return ""
    return re.sub(r"\D", "", num)


def _phone_numbers_match(num1: str | None, num2: str | None) -> bool:
    """Check if two phone numbers match, allowing for country code prefixes."""
    d1 = _normalize_phone(num1)
    d2 = _normalize_phone(num2)
    if not d1 or not d2:
        return False
    if d1 == d2:
        return True
    # Match last 10 digits (standard for mobile numbers in India/US)
    if len(d1) >= 10 and len(d2) >= 10 and d1[-10:] == d2[-10:]:
        return True
    return False


class SmsService:
    """Service to send SMS alerts to highway assistance and process incoming replies."""

    async def send_emergency_alert(self, emergency_id: str) -> Optional[EmergencySmsLog]:
        """Format and send emergency alert SMS to TOLL_ASSISTANCE_PHONE_NUMBER."""
        try:
            async with async_session() as db:
                # 1. Fetch Emergency record
                em_res = await db.execute(
                    select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
                )
                emergency = em_res.scalar_one_or_none()
                if not emergency:
                    logger.error(f"[SMS] Emergency {emergency_id} not found for SMS alert.")
                    return None

                # 2. Fetch Vehicle
                veh_plate = "MH-01-AB-1234"
                if emergency.vehicle_id:
                    veh_res = await db.execute(
                        select(Vehicle).where(Vehicle.id == emergency.vehicle_id)
                    )
                    vehicle = veh_res.scalar_one_or_none()
                    if vehicle and vehicle.plate_number:
                        veh_plate = vehicle.plate_number

                # 3. Fetch HighwayAssistance record
                assist_name = "Highway Assistance Plaza"
                assist_dist = 0.0
                assist_res = await db.execute(
                    select(HighwayAssistance)
                    .where(HighwayAssistance.emergency_id == emergency.id)
                    .limit(1)
                )
                assist = assist_res.scalar_one_or_none()
                if assist:
                    if assist.assistance_name:
                        assist_name = assist.assistance_name
                    if assist.distance_km is not None:
                        assist_dist = assist.distance_km

                # 4. Format data
                short_id = emergency.id.replace("-", "")[-8:].upper()
                microsleep_count = emergency.microsleep_count if emergency.microsleep_count is not None else 2
                count_str = (
                    f"{microsleep_count} separate microsleep events detected."
                    if microsleep_count != 1
                    else "1 microsleep event detected."
                )

                if emergency.status == "DRIVER_RECOVERED":
                    recovery_status = "DRIVER RECOVERED (AWAKE)"
                else:
                    recovery_status = "UNRESPONSIVE / CRITICAL"

                lat_str = f"{emergency.latitude:.6f}" if emergency.latitude is not None else "12.971600"
                lon_str = f"{emergency.longitude:.6f}" if emergency.longitude is not None else "77.594600"

                # 5. Build SMS Body
                sms_body = (
                    "SMARTDRIVE GUARDIAN EMERGENCY ALERT\n\n"
                    f"Emergency ID: #{short_id}\n"
                    f"Vehicle: {veh_plate}\n"
                    f"{count_str}\n"
                    f"Driver recovery status: {recovery_status}\n"
                    f"Location: {lat_str}, {lon_str}\n"
                    f"Nearest assistance: {assist_name}\n"
                    f"Distance: {assist_dist:.1f} km\n\n"
                    "Highway assistance is requested.\n\n"
                    "Reply:\n"
                    f"ACCEPT {short_id}\n"
                    "or\n"
                    f"REJECT {short_id}\n\n"
                    "SmartDrive Guardian"
                )

                to_number = settings.TOLL_ASSISTANCE_PHONE_NUMBER
                from_number = settings.TWILIO_PHONE_NUMBER
                account_sid = settings.TWILIO_ACCOUNT_SID
                auth_token = settings.TWILIO_AUTH_TOKEN

                sms_log = EmergencySmsLog(
                    emergency_id=emergency.id,
                    to_phone_number=to_number or "UNCONFIGURED",
                    from_phone_number=from_number or None,
                    sms_body=sms_body,
                    sent_at=datetime.now(timezone.utc),
                )

                # Check if Twilio is configured
                if not (account_sid and auth_token and from_number and to_number):
                    err_msg = (
                        "Twilio credentials or TOLL_ASSISTANCE_PHONE_NUMBER not fully configured. "
                        "SMS not dispatched to carrier."
                    )
                    logger.warning(f"[SMS] {err_msg}")
                    sms_log.sms_status = "SMS_FAILED"
                    sms_log.error_message = err_msg
                    db.add(sms_log)
                    await db.commit()

                    await manager.broadcast_to_all({
                        "type": "SMS_STATUS_UPDATE",
                        "emergency_id": emergency.id,
                        "sms_status": "SMS_FAILED",
                        "error": err_msg,
                    })
                    return sms_log

                # Dispatch via Twilio REST API
                try:
                    from twilio.rest import Client

                    client = Client(account_sid, auth_token)
                    status_cb = settings.TWILIO_STATUS_CALLBACK_URL or None

                    # Run synchronous Twilio call in worker thread
                    message = await asyncio.to_thread(
                        client.messages.create,
                        to=to_number,
                        from_=from_number,
                        body=sms_body,
                        status_callback=status_cb,
                    )

                    sms_log.sms_message_sid = message.sid
                    sms_log.sms_status = "SMS_SENT"
                    db.add(sms_log)
                    await db.commit()

                    logger.info(
                        f"[SMS] Emergency alert SMS dispatched: SID={message.sid} to={to_number} emergency={emergency.id}"
                    )

                    await manager.broadcast_to_all({
                        "type": "SMS_STATUS_UPDATE",
                        "emergency_id": emergency.id,
                        "sms_status": "SMS_SENT",
                        "message_sid": message.sid,
                        "to_number": to_number,
                    })
                    return sms_log

                except Exception as send_err:
                    logger.error(f"[SMS] Twilio message create error: {send_err}", exc_info=True)
                    sms_log.sms_status = "SMS_FAILED"
                    sms_log.error_message = str(send_err)
                    db.add(sms_log)
                    await db.commit()

                    await manager.broadcast_to_all({
                        "type": "SMS_STATUS_UPDATE",
                        "emergency_id": emergency.id,
                        "sms_status": "SMS_FAILED",
                        "error": str(send_err),
                    })
                    return sms_log

        except Exception as exc:
            logger.error(f"[SMS] Error in send_emergency_alert for {emergency_id}: {exc}", exc_info=True)
            return None

    async def handle_incoming_sms(
        self,
        from_number: str,
        body: str,
        message_sid: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Process inbound SMS reply from toll assistance.

        Returns (success: bool, reply_twiml_text: str, emergency_id: Optional[str]).
        """
        # Validate sender phone number against configured TOLL_ASSISTANCE_PHONE_NUMBER
        configured_toll = settings.TOLL_ASSISTANCE_PHONE_NUMBER
        if configured_toll and not _phone_numbers_match(from_number, configured_toll):
            logger.warning(
                f"[SMS] Unauthorized sender {from_number} does not match configured TOLL_ASSISTANCE_PHONE_NUMBER ({configured_toll})"
            )
            return (
                False,
                "SmartDrive Guardian: Unauthorized sender phone number.",
                None,
            )

        # Parse command: ACCEPT or REJECT (and optional Emergency ID)
        cleaned_body = body.strip()
        match = re.match(
            r"^(ACCEPT|REJECT)(?:\s+([A-Za-z0-9\-]+))?", cleaned_body, re.IGNORECASE
        )
        if not match:
            return (
                False,
                "SmartDrive Guardian: Invalid format. Reply with: ACCEPT <Emergency ID> or REJECT <Emergency ID>.",
                None,
            )

        action = match.group(1).upper()
        target_token = match.group(2)
        if target_token:
            target_token = target_token.strip().replace("#", "")

        # Find matching emergency
        target_emergency: Optional[EmergencyEvent] = None

        if target_token:
            # Match by full ID or last 8 characters
            q = select(EmergencyEvent).where(
                (EmergencyEvent.id == target_token)
                | (EmergencyEvent.id.ilike(f"%{target_token}"))
            )
            res = await db.execute(q)
            target_emergency = res.scalar_one_or_none()

            if not target_emergency:
                return (
                    False,
                    f"SmartDrive Guardian: Emergency #{target_token} not found.",
                    None,
                )
        else:
            # If no ID specified, look for active emergencies
            q = (
                select(EmergencyEvent)
                .where(EmergencyEvent.status.in_(["ACTIVE", "DRIVER_RECOVERED"]))
                .order_by(EmergencyEvent.detected_at.desc())
            )
            res = await db.execute(q)
            active_events = list(res.scalars().all())

            if not active_events:
                return (
                    False,
                    "SmartDrive Guardian: No active emergencies found to respond to.",
                    None,
                )
            if len(active_events) > 1:
                return (
                    False,
                    "SmartDrive Guardian: Multiple active emergencies. Please specify ID: ACCEPT <Emergency ID>",
                    None,
                )
            target_emergency = active_events[0]

        short_id = target_emergency.id.replace("-", "")[-8:].upper()

        # Verify emergency is still eligible for response
        if target_emergency.status not in ("ACTIVE", "DRIVER_RECOVERED"):
            return (
                False,
                f"SmartDrive Guardian: Emergency #{short_id} is already in status '{target_emergency.status}'.",
                target_emergency.id,
            )

        now = datetime.now(timezone.utc)

        if action == "ACCEPT":
            response_msg = "Highway assistance team has accepted the request."
            target_emergency.status = "ASSISTANCE_RESPONDED"
            target_emergency.response_message = response_msg
            target_emergency.responded_at = now

            # Update HighwayAssistance table record if exists
            try:
                assist_res = await db.execute(
                    select(HighwayAssistance)
                    .where(HighwayAssistance.emergency_id == target_emergency.id)
                    .limit(1)
                )
                assist = assist_res.scalar_one_or_none()
                if assist:
                    assist.status = "ACCEPTED"
                    assist.resolved_at = now
            except Exception as e:
                logger.error(f"[SMS] Could not update HighwayAssistance for {target_emergency.id}: {e}")

            # Notify in-memory risk engine
            try:
                from app.risk_engine.emergency_engine import emergency_engine
                emergency_engine.on_emergency_responded(target_emergency.id)
            except Exception as eng_err:
                logger.debug(f"[SMS] Emergency engine sync: {eng_err}")

            reply_text = f"SmartDrive Guardian: Emergency #{short_id} has been ACCEPTED. Dispatch details recorded."

        else:  # REJECT
            response_msg = "Highway assistance rejected the request."
            target_emergency.status = "ASSISTANCE_RESPONDED"
            target_emergency.response_message = response_msg
            target_emergency.responded_at = now

            try:
                assist_res = await db.execute(
                    select(HighwayAssistance)
                    .where(HighwayAssistance.emergency_id == target_emergency.id)
                    .limit(1)
                )
                assist = assist_res.scalar_one_or_none()
                if assist:
                    assist.status = "REJECTED"
                    assist.resolved_at = now
            except Exception as e:
                logger.error(f"[SMS] Could not update HighwayAssistance for {target_emergency.id}: {e}")

            reply_text = f"SmartDrive Guardian: Emergency #{short_id} has been marked REJECTED."

        # Update or create EmergencySmsLog
        log_res = await db.execute(
            select(EmergencySmsLog)
            .where(EmergencySmsLog.emergency_id == target_emergency.id)
            .order_by(EmergencySmsLog.sent_at.desc())
            .limit(1)
        )
        sms_log = log_res.scalar_one_or_none()
        if not sms_log:
            sms_log = EmergencySmsLog(
                emergency_id=target_emergency.id,
                to_phone_number=from_number,
                sent_at=now,
            )
            db.add(sms_log)

        response_status_standard = "ACCEPTED" if action.startswith("ACCEPT") else "REJECTED"

        sms_log.assistance_phone_number = from_number
        sms_log.assistance_response_status = response_status_standard
        sms_log.assistance_response_message = response_msg
        sms_log.assistance_responded_at = now

        await db.commit()

        # Broadcast ASSISTANCE_RESPONSE via existing WebSocket manager
        try:
            await manager.broadcast_to_all({
                "type": "ASSISTANCE_RESPONSE",
                "emergency_id": target_emergency.id,
                "status": "ASSISTANCE_RESPONDED",
                "response_status": response_status_standard,
                "message": response_msg,
                "responded_at": now.isoformat(),
                "phone_number": from_number,
            })
            logger.info(
                f"[SMS] ASSISTANCE_RESPONSE broadcast: emergency={target_emergency.id} action={response_status_standard} sender={from_number}"
            )
        except Exception as ws_err:
            logger.error(f"[SMS] WebSocket broadcast error: {ws_err}")

        return True, reply_text, target_emergency.id

    async def handle_delivery_status(
        self,
        message_sid: str,
        message_status: str,
        db: AsyncSession,
    ):
        """Update delivery status callback from Twilio."""
        try:
            res = await db.execute(
                select(EmergencySmsLog).where(EmergencySmsLog.sms_message_sid == message_sid)
            )
            sms_log = res.scalar_one_or_none()
            if not sms_log:
                logger.warning(f"[SMS] Delivery callback for unknown message SID {message_sid}")
                return

            status_map = {
                "delivered": "SMS_DELIVERED",
                "undelivered": "SMS_FAILED",
                "failed": "SMS_FAILED",
                "sent": "SMS_SENT",
                "queued": "SMS_PENDING",
            }
            new_status = status_map.get(message_status.lower(), f"SMS_{message_status.upper()}")
            sms_log.sms_status = new_status
            sms_log.delivery_updated_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"[SMS] Updated delivery status for SID={message_sid}: {new_status}")

            await manager.broadcast_to_all({
                "type": "SMS_STATUS_UPDATE",
                "emergency_id": sms_log.emergency_id,
                "sms_status": new_status,
                "message_sid": message_sid,
            })
        except Exception as exc:
            logger.error(f"[SMS] Error in handle_delivery_status: {exc}", exc_info=True)


sms_service = SmsService()
