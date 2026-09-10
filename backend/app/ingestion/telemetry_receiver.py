"""Telemetry receiver — receives speed/gear data. Stub for Phase 1."""


class TelemetryReceiver:
    """Receives vehicle telemetry (speed, gear) — simulated for prototype."""

    def __init__(self):
        self.speed_kmh: float = 0.0
        self.gear: str = "D"

    def update(self, speed_kmh: float, gear: str = "D"):
        self.speed_kmh = speed_kmh
        self.gear = gear
