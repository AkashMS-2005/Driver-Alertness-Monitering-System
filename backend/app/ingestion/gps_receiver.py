"""GPS receiver — receives location data. Stub for Phase 1."""


class GPSReceiver:
    """Receives GPS coordinates — simulated for prototype."""

    def __init__(self):
        self.latitude: float = 0.0
        self.longitude: float = 0.0
        self.heading: float = 0.0

    def update(self, lat: float, lon: float, heading: float = 0.0):
        self.latitude = lat
        self.longitude = lon
        self.heading = heading
