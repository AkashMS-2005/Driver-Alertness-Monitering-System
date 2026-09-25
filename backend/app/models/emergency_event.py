"""EmergencyEvent model — critical safety emergencies.

Status state machine:
  ACTIVE              → emergency just triggered (auto or manual)
  DRIVER_RECOVERED    → driver NORMAL + drowsiness ≤ 50% for recovery window
  ASSISTANCE_RESPONDED → toll/highway responded (takes priority over recovery)
  CANCELLED           → driver cancelled after recovery (only if assistance hasn't responded)
  RESOLVED            → fully closed (assistance responded + handled)
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Float, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("owners.id", ondelete="SET NULL"), nullable=True
    )
    emergency_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g. "AUTO_DROWSINESS" or "DRIVER_EMERGENCY"
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ACTIVE"
    )  # ACTIVE, DRIVER_RECOVERED, ASSISTANCE_RESPONDED, CANCELLED, RESOLVED
    trigger_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MANUAL"
    )  # "AUTO_DROWSINESS" or "MANUAL"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Location at time of trigger
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    place_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # AI metrics at time of trigger
    microsleep_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    drowsiness_percentage: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)

    # Timestamps
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Assistance response
    response_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )  # "SMS" or "MANUAL"
    assistance_response_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True, default=None
    )  # "ACCEPTED" or "REJECTED"
    response_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cancellation
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolution
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    trip = relationship("Trip", back_populates="emergency_events")
    vehicle = relationship("Vehicle", back_populates="emergency_events")
