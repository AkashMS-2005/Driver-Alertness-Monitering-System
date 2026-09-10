"""Notification service — sends alerts to owners via WebSocket and persists them."""

import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.alert import Alert
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")


class NotificationService:
    """Creates alerts and pushes them to owner dashboards."""

    @staticmethod
    async def create_alert(
        db: AsyncSession,
        vehicle_id: str,
        owner_id: str,
        alert_type: str,
        severity: str,
        message: str,
    ) -> Alert:
        """Create an alert record and push it to the owner dashboard."""
        alert = Alert(
            vehicle_id=vehicle_id,
            owner_id=owner_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
        )
        db.add(alert)
        await db.flush()
        await db.refresh(alert)

        # Push to owner dashboard immediately
        payload = {
            "event_type": "ALERT_NEW",
            "alert_id": alert.id,
            "vehicle_id": vehicle_id,
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_to_owner(owner_id, payload)
        logger.info(
            f"Alert created: type={alert_type} severity={severity} owner={owner_id}"
        )
        return alert

    @staticmethod
    async def acknowledge_alert(db: AsyncSession, alert_id: str) -> bool:
        """Mark an alert as acknowledged."""
        from sqlalchemy import select

        result = await db.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if alert:
            alert.acknowledged = True
            await db.flush()
            return True
        return False
