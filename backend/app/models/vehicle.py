"""Vehicle model — registered vehicle being monitored."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("owners.id", ondelete="CASCADE"), nullable=False
    )
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    make: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    owner = relationship("Owner", back_populates="vehicles")
    trips = relationship("Trip", back_populates="vehicle", lazy="selectin")
    safety_events = relationship("SafetyEvent", back_populates="vehicle", lazy="selectin")
    alerts = relationship("Alert", back_populates="vehicle", lazy="selectin")
    locations = relationship("Location", back_populates="vehicle", lazy="selectin")
    highway_assistances = relationship(
        "HighwayAssistance", back_populates="vehicle", lazy="selectin"
    )
    emergency_events = relationship(
        "EmergencyEvent", back_populates="vehicle", lazy="selectin"
    )
