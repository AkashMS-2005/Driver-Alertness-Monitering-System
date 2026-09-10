"""Service stubs for Phase 1 — will be fully implemented in later phases."""


class TripService:
    """Manages trip lifecycle — auto-start, end, status updates."""

    @staticmethod
    async def auto_start_trip(vehicle_id: str, db) -> dict:
        """Auto-start a trip when vehicle begins moving. (Stub for Phase 1)"""
        pass

    @staticmethod
    async def end_trip(trip_id: str, db) -> dict:
        """End an active trip. (Stub for Phase 1)"""
        pass
