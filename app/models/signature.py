from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Signature(Base):
    __tablename__ = "signatures"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soap_note_id: Mapped[int] = mapped_column(ForeignKey("soap_notes.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    method: Mapped[str] = mapped_column(String, default="CONFIRMATION", nullable=False)

    soap_note = relationship("SOAPNote", back_populates="signature")
    doctor = relationship("Doctor")
