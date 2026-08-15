import enum
from datetime import datetime, timezone
from sqlalchemy import Enum, ForeignKey, Integer, String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.core.encrypted_type import EncryptedText

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
    # order_by is not cosmetic. Without it PostgreSQL returns rows in whatever
    # order it finds them, which is not insertion order and not stable. Found
    # during the Module 9.2 manual API run on 15 Aug 2026: GET .../transcript
    # returned the segment starting at 38.12s first, ahead of the one starting
    # at 0.64s.
    #
    # A client rendering that list shows the consultation out of sequence.
    # SOAP generation is unaffected: soap_note_service.py already applies its
    # own .order_by(TranscriptSegment.start_time) when it reads segments.
    #
    # Ordering here rather than in the endpoint means every consumer inherits
    # it, including anything added later that forgets to sort — which is how
    # this defect reached the API response in the first place.
    segments = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_time",
    )

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    speaker_role: Mapped[str] = mapped_column(String, nullable=False)  # "DOCTOR" or "PATIENT"
    text: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    transcript = relationship("Transcript", back_populates="segments")
