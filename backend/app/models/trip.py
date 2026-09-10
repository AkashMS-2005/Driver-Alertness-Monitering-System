"""Trip model — a highway driving session for a vehicle."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    vehicle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ACTIVE"
    )  # ACTIVE, PAUSED, COMPLETED, EMERGENCY_STOPPED
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    start_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)

    # Relationships
    vehicle = relationship("Vehicle", back_populates="trips")
    safety_events = relationship("SafetyEvent", back_populates="trip", lazy="selectin")
    locations = relationship("Location", back_populates="trip", lazy="selectin")
    highway_assistances = relationship(
        "HighwayAssistance", back_populates="trip", lazy="selectin"
    )
    emergency_events = relationship(
        "EmergencyEvent", back_populates="trip", lazy="selectin"
    )
