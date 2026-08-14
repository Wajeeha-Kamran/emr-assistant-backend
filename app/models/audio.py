from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class AudioMetadata(Base):
    __tablename__ = "audio_metadata"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("consultation_sessions.id"), unique=True, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    retention_marked_for_deletion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session = relationship("ConsultationSession", back_populates="audio")
