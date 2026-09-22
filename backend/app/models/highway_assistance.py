"""HighwayAssistance model — roadside assistance requests."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class HighwayAssistance(Base):
    __tablename__ = "highway_assistances"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trip_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    emergency_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # Links to EmergencyEvent.id (no FK constraint to allow orphan cleanup)
    assistance_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # See AssistanceType enum
    assistance_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # e.g. "Nelamangala Toll Plaza (NH-48)"
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="REQUESTED"
    )  # See AssistanceStatus enum
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    trip = relationship("Trip", back_populates="highway_assistances")
    vehicle = relationship("Vehicle", back_populates="highway_assistances")
