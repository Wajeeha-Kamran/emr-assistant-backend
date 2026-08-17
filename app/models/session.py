import enum
from datetime import datetime, timezone
from sqlalchemy import Enum, ForeignKey, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class SessionStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    RECORDING = "RECORDING"
    STOPPED = "STOPPED"
    FINALIZED = "FINALIZED"
    # A consultation the doctor abandoned before any audio was uploaded.
    #
    # Reachable only from INITIATED or RECORDING. Once audio exists the
    # consultation holds clinical content and is finished or recovered through
    # the attention list instead — it is never discarded.
    DISCARDED = "DISCARDED"

class ConsultationSession(Base):
    __tablename__ = "consultation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), nullable=False, index=True)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.INITIATED, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Recorded rather than deleting the row. An abandoned consultation holds no
    # clinical content, but the fact that one was started and abandoned is
    # itself a thing an audit would want to see.
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audio = relationship("AudioMetadata", back_populates="session", uselist=False)
    transcript = relationship("Transcript", back_populates="session", uselist=False)
