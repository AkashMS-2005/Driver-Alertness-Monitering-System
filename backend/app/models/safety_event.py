"""SafetyEvent model — records each safety-related event during a trip."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class SafetyEvent(Base):
    __tablename__ = "safety_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # DROWSINESS_WARNING, FATIGUE_WARNING, DISTRACTION_WARNING, etc.
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # SAFE, WARNING, HIGH_RISK, CRITICAL
    driver_status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # Alert, Drowsy, Fatigued, Distracted, Critical
    distraction_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="Normal"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    fatigue_level: Mapped[int | None] = mapped_column(nullable=True)  # 0-100 smoothed
    speed_kmh: Mapped[float | None] = mapped_column(nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    trip = relationship("Trip", back_populates="safety_events")
    vehicle = relationship("Vehicle", back_populates="safety_events")
