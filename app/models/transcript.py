import enum
from datetime import datetime, timezone
from sqlalchemy import Enum, ForeignKey, Integer, String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class TranscriptStatus(str, enum.Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"

class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("consultation_sessions.id"), unique=True, nullable=False)
    status: Mapped[TranscriptStatus] = mapped_column(Enum(TranscriptStatus), default=TranscriptStatus.processing, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session = relationship("ConsultationSession", back_populates="transcript")
    segments = relationship("TranscriptSegment", back_populates="transcript", cascade="all, delete-orphan")

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    speaker_role: Mapped[str] = mapped_column(String, nullable=False)  # "DOCTOR" or "PATIENT"
    text: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    transcript = relationship("Transcript", back_populates="segments")
