"""Risk Engine context — combines AI + GPS + telemetry.

Stub for Phase 1. Full implementation in Phase 4.
"""


class RiskContext:
    """Aggregates current AI state, GPS position, and vehicle telemetry."""

    def __init__(self):
        self.speed_kmh: float = 0.0
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.gear: str | None = None
        self.ai_status: dict = {}
