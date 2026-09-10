"""Shared enumerations for SmartDrive Guardian."""

from enum import Enum


class DriverStatus(str, Enum):
    """Driver state as determined by AI — human-readable, no raw metrics."""
    ALERT = "Alert"
    DROWSY = "Drowsy"
    FATIGUED = "Fatigued"
    DISTRACTED = "Distracted"
    CRITICAL = "Critical"
    UNKNOWN = "Unknown"


class RiskLevel(str, Enum):
    """Overall risk assessment — used in state machine and dashboards."""
    SAFE = "SAFE"
    WARNING = "WARNING"
    HIGH_RISK = "HIGH_RISK"
    CRITICAL = "CRITICAL"


class SafetyState(str, Enum):
    """Risk Engine state machine states."""
    SAFE = "SAFE"
    WARNING = "WARNING"
    HIGH_RISK = "HIGH_RISK"
    HIGHWAY_ASSISTANCE = "HIGHWAY_ASSISTANCE"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class DistractionStatus(str, Enum):
    """Distraction assessment."""
    NORMAL = "Normal"
    MILD = "Mild"
    SIGNIFICANT = "Significant"
    SEVERE = "Severe"


class TripStatus(str, Enum):
    """Trip lifecycle states."""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class AlertType(str, Enum):
    """Types of alerts sent to owners / displayed on dashboard."""
    DROWSINESS_WARNING = "DROWSINESS_WARNING"
    FATIGUE_WARNING = "FATIGUE_WARNING"
    DISTRACTION_WARNING = "DISTRACTION_WARNING"
    HIGH_RISK = "HIGH_RISK"
    CRITICAL_RISK = "CRITICAL_RISK"
    EMERGENCY = "EMERGENCY"
    HIGHWAY_ASSISTANCE = "HIGHWAY_ASSISTANCE"
    AI_MONITORING_UNAVAILABLE = "AI_MONITORING_UNAVAILABLE"
    DRIVER_RECOVERED = "DRIVER_RECOVERED"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AIConnectionStatus(str, Enum):
    """Connection state between Laptop 2 and Laptop 1 AI service."""
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


class AssistanceType(str, Enum):
    """Highway assistance request types."""
    TOWING = "TOWING"
    MECHANICAL = "MECHANICAL"
    MEDICAL = "MEDICAL"
    FUEL = "FUEL"
    GENERAL = "GENERAL"


class AssistanceStatus(str, Enum):
    """Highway assistance request status."""
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EmergencyType(str, Enum):
    """Emergency event types."""
    DRIVER_INCAPACITATED = "DRIVER_INCAPACITATED"
    COLLISION_RISK = "COLLISION_RISK"
    VEHICLE_STOPPED_HIGHWAY = "VEHICLE_STOPPED_HIGHWAY"
    MANUAL_SOS = "MANUAL_SOS"


class EmergencyStatus(str, Enum):
    """Emergency event status."""
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    SERVICES_NOTIFIED = "SERVICES_NOTIFIED"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class WebSocketEventType(str, Enum):
    """WebSocket event types pushed to dashboards."""
    SAFETY_STATUS_UPDATE = "SAFETY_STATUS_UPDATE"
    TRIP_UPDATE = "TRIP_UPDATE"
    LOCATION_UPDATE = "LOCATION_UPDATE"
    ALERT_NEW = "ALERT_NEW"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    ASSISTANCE_UPDATE = "ASSISTANCE_UPDATE"
    EMERGENCY_UPDATE = "EMERGENCY_UPDATE"
    AI_CONNECTION_STATUS_UPDATE = "AI_CONNECTION_STATUS_UPDATE"
    SPEED_UPDATE = "SPEED_UPDATE"
