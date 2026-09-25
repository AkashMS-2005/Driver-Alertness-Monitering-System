"""EmergencySmsLog model — tracks SMS alerts sent to highway assistance and inbound replies."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class EmergencySmsLog(Base):
    __tablename__ = "emergency_sms_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    emergency_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False
    )
    to_phone_number: Mapped[str] = mapped_column(String(30), nullable=False)
    from_phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sms_message_sid: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    sms_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="SMS_PENDING"
    )  # SMS_PENDING, SMS_SENT, SMS_DELIVERED, SMS_FAILED
    sms_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    delivery_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Inbound reply tracking
    assistance_phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    assistance_response_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # ACCEPTED, REJECTED
    assistance_response_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    assistance_responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
