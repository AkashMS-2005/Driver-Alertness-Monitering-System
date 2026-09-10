"""Import all models here so Alembic and Base.metadata can see them."""

from app.db.database import Base  # noqa: F401
from app.models.owner import Owner  # noqa: F401
from app.models.vehicle import Vehicle  # noqa: F401
from app.models.trip import Trip  # noqa: F401
from app.models.safety_event import SafetyEvent  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.location import Location  # noqa: F401
from app.models.highway_assistance import HighwayAssistance  # noqa: F401
from app.models.emergency_event import EmergencyEvent  # noqa: F401
