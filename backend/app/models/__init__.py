"""Model package — import all models for easy access."""

from app.models.owner import Owner
from app.models.vehicle import Vehicle
from app.models.trip import Trip
from app.models.safety_event import SafetyEvent
from app.models.alert import Alert
from app.models.location import Location
from app.models.highway_assistance import HighwayAssistance
from app.models.emergency_event import EmergencyEvent
from app.models.ai_connection_state import AIConnectionState

__all__ = [
    "Owner",
    "Vehicle",
    "Trip",
    "SafetyEvent",
    "Alert",
    "Location",
    "HighwayAssistance",
    "EmergencyEvent",
    "AIConnectionState",
]
