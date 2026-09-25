"""Emergency Engine — Automatic drowsiness-based emergency escalation.

This module is the core of the automatic emergency system.

Primary trigger rule (per specification):
  microsleep_count >= 2
  → Automatic emergency triggered.
  → No drowsiness percentage condition is required as a blocker.

Additional rules:
  - Counts SEPARATE microsleep EVENTS (state transitions into MICROSLEEP).
  - Does NOT count every frame of MICROSLEEP.
  - Only ONE active emergency per vehicle/trip at a time.
  - Recovery requires NORMAL + drowsiness <= 50% continuously for
    RECOVERY_CONFIRMATION_SECONDS (default 10s).
  - After CANCELLED or RESOLVED, waits EMERGENCY_COOLDOWN_SECONDS (default 60s)
    before allowing a new automatic emergency.

State machine (in-memory, per trip):
  NO_ACTIVE_EMERGENCY
      → (microsleep_count >= 2) → ACTIVE
  ACTIVE
      → (assistance responds) → ASSISTANCE_RESPONDED → RESOLVED
      → (driver recovers 10s) → DRIVER_RECOVERED
  DRIVER_RECOVERED
      → (driver cancels) → CANCELLED
      → (assistance responds — takes priority) → ASSISTANCE_RESPONDED
  ASSISTANCE_RESPONDED → RESOLVED (immediate)
  CANCELLED / RESOLVED → [cooldown 60s] → NO_ACTIVE_EMERGENCY
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("smartdrive.emergency_engine")


class EmergencyEngine:
    """In-memory singleton that tracks microsleep events and manages auto-emergencies.

    NOTE: This is in-memory state. It resets on backend restart.
    All persistent state is written to the database via EmergencyService.
    """

    def __init__(self):
        # --- Microsleep event tracking ---
        self._previous_state: str = "NORMAL"       # Last state seen
        self._microsleep_count: int = 0             # Separate microsleep events

        # --- Active emergency tracking ---
        self._active_emergency_id: Optional[str] = None
        self._active_emergency_status: Optional[str] = None  # mirrors DB status

        # --- Recovery timer ---
        self._recovery_start_time: Optional[float] = None  # monotonic timestamp

        # --- Cooldown tracking ---
        self._cooldown_until: float = 0.0           # monotonic timestamp

        # --- Processing lock (prevent concurrent trigger attempts) ---
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------------
    # Public Properties
    # ----------------------------------------------------------------

    @property
    def microsleep_count(self) -> int:
        return self._microsleep_count

    @property
    def active_emergency_id(self) -> Optional[str]:
        return self._active_emergency_id

    @property
    def has_active_emergency(self) -> bool:
        return self._active_emergency_id is not None and self._active_emergency_status in (
            "ACTIVE", "DRIVER_RECOVERED", "TRIGGERING"
        )

    # ----------------------------------------------------------------
    # Trip Reset
    # ----------------------------------------------------------------

    def reset_for_new_trip(self):
        """Call when a new trip starts — resets counters and emergency state."""
        self._previous_state = "NORMAL"
        self._microsleep_count = 0
        self._active_emergency_id = None
        self._active_emergency_status = None
        self._recovery_start_time = None
        self._cooldown_until = 0.0
        logger.info("EmergencyEngine: reset for new trip")

    # ----------------------------------------------------------------
    # Main AI Event Handler
    # ----------------------------------------------------------------

    async def on_ai_event(
        self,
        state: str,
        drowsiness_percentage: float,
        vehicle_id: str,
        trip_id: str,
        alertness_score: int = 100,
        head_state: str = "NORMAL",
    ):
        """Called on every AI frame. Handles microsleep counting + emergency logic.

        This is the ONLY entry point from the AI pipeline. It must be fast —
        any DB writes are done via asyncio.create_task to avoid blocking.

        Args:
            state:               Current AI state (NORMAL / DROWSY / MICROSLEEP).
            drowsiness_percentage: PERCLOS-based drowsiness % (0-100).
            vehicle_id:          Active vehicle UUID.
            trip_id:             Active trip UUID.
            alertness_score:     Fusion-based alertness score (0-100).
            head_state:          Head pose state (NORMAL / DEVIATING / DISTRACTED).
        """
        async with self._lock:
            await self._process_event(state, drowsiness_percentage, vehicle_id, trip_id)

    async def _process_event(
        self,
        state: str,
        drowsiness_percentage: float,
        vehicle_id: str,
        trip_id: str,
    ):
        # ------------------------------------------------------------------
        # 1. Microsleep event counting (state transition logic)
        # ------------------------------------------------------------------
        if state == "MICROSLEEP" and self._previous_state != "MICROSLEEP":
            self._microsleep_count += 1
            logger.warning(
                f"MICROSLEEP EVENT #{self._microsleep_count} detected "
                f"(prev_state={self._previous_state})"
            )

        self._previous_state = state

        # ------------------------------------------------------------------
        # 2. No active emergency path — check trigger condition
        # ------------------------------------------------------------------
        if not self.has_active_emergency:
            await self._check_trigger(
                state, drowsiness_percentage, vehicle_id, trip_id
            )
            return

        # ------------------------------------------------------------------
        # 3. Active emergency path — handle recovery timer
        # ------------------------------------------------------------------
        em_status = self._active_emergency_status

        if em_status == "ACTIVE":
            await self._handle_recovery_timer(
                state, drowsiness_percentage, vehicle_id
            )
        elif em_status == "DRIVER_RECOVERED":
            # If driver becomes drowsy again during DRIVER_RECOVERED window,
            # push back to ACTIVE and disable cancel
            if state in ("DROWSY", "MICROSLEEP") or drowsiness_percentage > 50:
                logger.info(
                    "Driver became drowsy again during DRIVER_RECOVERED — "
                    "reverting to ACTIVE"
                )
                self._active_emergency_status = "ACTIVE"
                self._recovery_start_time = None
                asyncio.create_task(
                    self._broadcast_emergency_update(
                        self._active_emergency_id, "ACTIVE", drowsiness_percentage
                    )
                )

    # ----------------------------------------------------------------
    # Trigger Check
    # ----------------------------------------------------------------

    async def _check_trigger(
        self,
        state: str,
        drowsiness_percentage: float,
        vehicle_id: str,
        trip_id: str,
    ):
        """Decide whether to fire an automatic emergency."""
        # Cooldown guard
        if time.monotonic() < self._cooldown_until:
            return

        # PRIMARY TRIGGER: microsleep_count >= 2
        # This is the primary automatic emergency condition.
        # (No drowsiness % guard — the microsleep count alone is the trigger
        #  per the project specification. Two separate microsleep events are
        #  clinically significant regardless of the current PERCLOS value.)
        if self._microsleep_count >= 2:
            self._active_emergency_status = "TRIGGERING"  # Block concurrent frame re-trigger
            logger.warning(
                f"[EMERGENCY] AUTOMATIC EMERGENCY TRIGGERED — "
                f"microsleep_count={self._microsleep_count} "
                f"drowsiness={drowsiness_percentage:.1f}% "
                f"vehicle={vehicle_id} trip={trip_id}"
            )
            asyncio.create_task(
                self._fire_emergency(
                    vehicle_id, trip_id, drowsiness_percentage
                )
            )

    # ----------------------------------------------------------------
    # Fire Emergency (DB + WebSocket via EmergencyService)
    # ----------------------------------------------------------------

    async def _fire_emergency(
        self,
        vehicle_id: str,
        trip_id: str,
        drowsiness_percentage: float,
    ):
        """Create the EmergencyEvent + HighwayAssistance + notify owner."""
        try:
            from app.services.emergency_service import emergency_service
            from app.db.database import async_session

            async with async_session() as db:
                # Double-check: no active emergency already in DB
                existing = await emergency_service.get_active_emergency(vehicle_id, db)
                if existing:
                    # Already tracked — sync in-memory state
                    self._active_emergency_id = existing.id
                    self._active_emergency_status = existing.status
                    logger.debug(
                        f"Emergency already active in DB: {existing.id} — skipping creation"
                    )
                    return

                emergency = await emergency_service.create_auto_emergency(
                    vehicle_id=vehicle_id,
                    trip_id=trip_id,
                    microsleep_count=self._microsleep_count,
                    drowsiness_percentage=drowsiness_percentage,
                    db=db,
                )
                await db.commit()

            # Update in-memory state AFTER successful DB commit
            self._active_emergency_id = emergency.id
            self._active_emergency_status = "ACTIVE"
            logger.warning(
                f"EMERGENCY CREATED — id={emergency.id} "
                f"microsleeps={self._microsleep_count} "
                f"drowsiness={drowsiness_percentage:.1f}%"
            )

        except Exception as exc:
            self._active_emergency_status = None
            logger.error(f"Failed to create automatic emergency: {exc}", exc_info=True)

    # ----------------------------------------------------------------
    # Recovery Timer
    # ----------------------------------------------------------------

    async def _handle_recovery_timer(
        self,
        state: str,
        drowsiness_percentage: float,
        vehicle_id: str,
    ):
        """Manage the 10-second recovery confirmation window."""
        from app.core.config import settings

        recovery_window = settings.RECOVERY_CONFIRMATION_SECONDS

        if state == "NORMAL" and drowsiness_percentage <= 50.0:
            # Start or continue recovery timer
            if self._recovery_start_time is None:
                self._recovery_start_time = time.monotonic()
                logger.info(
                    "Recovery timer started for emergency "
                    f"{self._active_emergency_id}"
                )
            else:
                elapsed = time.monotonic() - self._recovery_start_time
                if elapsed >= recovery_window:
                    logger.info(
                        f"DRIVER RECOVERED — elapsed={elapsed:.1f}s >= {recovery_window}s "
                        f"emergency={self._active_emergency_id}"
                    )
                    await self._mark_driver_recovered(drowsiness_percentage)
        else:
            # Driver not recovered — reset timer
            if self._recovery_start_time is not None:
                logger.info(
                    f"Recovery timer reset (state={state} drowsiness={drowsiness_percentage:.1f}%)"
                )
            self._recovery_start_time = None

    async def _mark_driver_recovered(self, drowsiness_percentage: float):
        """Transition emergency to DRIVER_RECOVERED."""
        emergency_id = self._active_emergency_id
        self._active_emergency_status = "DRIVER_RECOVERED"
        self._recovery_start_time = None

        try:
            from app.services.emergency_service import emergency_service
            from app.db.database import async_session

            async with async_session() as db:
                await emergency_service.mark_driver_recovered(
                    emergency_id, drowsiness_percentage, db
                )
                await db.commit()
        except Exception as exc:
            logger.error(f"Failed to persist DRIVER_RECOVERED: {exc}", exc_info=True)

    # ----------------------------------------------------------------
    # External state sync (called from API endpoints)
    # ----------------------------------------------------------------

    def on_emergency_responded(self, emergency_id: str):
        """Called when assistance responds — update in-memory state."""
        if self._active_emergency_id == emergency_id or self._active_emergency_id is None:
            self._active_emergency_status = "ASSISTANCE_RESPONDED"
            self._active_emergency_id = None
            self._recovery_start_time = None
            logger.info(f"ASSISTANCE RESPONSE RECEIVED — emergency={emergency_id}")

    def on_emergency_cancelled(self, emergency_id: str):
        """Called when driver cancels — set cooldown."""
        if self._active_emergency_id == emergency_id:
            self._active_emergency_status = "CANCELLED"
            self._recovery_start_time = None
            from app.core.config import settings
            self._cooldown_until = time.monotonic() + settings.EMERGENCY_COOLDOWN_SECONDS
            logger.info(
                f"EMERGENCY CANCELLED — emergency={emergency_id} "
                f"cooldown={settings.EMERGENCY_COOLDOWN_SECONDS}s"
            )
            # Do NOT reset _active_emergency_id immediately — keep until cooldown
            asyncio.create_task(self._clear_after_cooldown())

    def on_emergency_resolved(self, emergency_id: str):
        """Called when emergency is resolved — set cooldown."""
        if self._active_emergency_id == emergency_id:
            self._active_emergency_status = "RESOLVED"
            self._recovery_start_time = None
            from app.core.config import settings
            self._cooldown_until = time.monotonic() + settings.EMERGENCY_COOLDOWN_SECONDS
            logger.info(
                f"EMERGENCY RESOLVED — emergency={emergency_id} "
                f"cooldown={settings.EMERGENCY_COOLDOWN_SECONDS}s"
            )
            asyncio.create_task(self._clear_after_cooldown())

    async def _clear_after_cooldown(self):
        """After cooldown expires, clear active emergency and reset microsleep counter."""
        from app.core.config import settings
        await asyncio.sleep(settings.EMERGENCY_COOLDOWN_SECONDS)
        self._active_emergency_id = None
        self._active_emergency_status = None
        self._microsleep_count = 0  # Reset for next emergency window
        logger.info("Emergency cooldown complete — engine ready for new events")

    # ----------------------------------------------------------------
    # WebSocket broadcast helpers
    # ----------------------------------------------------------------

    async def _broadcast_emergency_update(
        self, emergency_id: Optional[str], status: str, drowsiness_percentage: float
    ):
        """Broadcast an EMERGENCY_UPDATED event to all owner dashboards."""
        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all_owners({
                "type": "EMERGENCY_UPDATED",
                "emergency_id": emergency_id,
                "status": status,
                "drowsiness_percentage": round(drowsiness_percentage, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast EMERGENCY_UPDATED: {exc}")


# Singleton — imported by risk engine and API routes
emergency_engine = EmergencyEngine()
