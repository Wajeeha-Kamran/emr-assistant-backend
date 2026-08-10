import enum
from datetime import datetime, timezone
from sqlalchemy import Enum, ForeignKey, Integer, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class SOAPNoteStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class SOAPSectionType(str, enum.Enum):
    SUBJECTIVE = "SUBJECTIVE"
    OBJECTIVE = "OBJECTIVE"
    ASSESSMENT = "ASSESSMENT"
    PLAN = "PLAN"


class SOAPNote(Base):
    __tablename__ = "soap_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("consultation_sessions.id"), unique=True, nullable=False, index=True)
    status: Mapped[SOAPNoteStatus] = mapped_column(Enum(SOAPNoteStatus), default=SOAPNoteStatus.DRAFT, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session = relationship("ConsultationSession")
    sections = relationship("SOAPSection", back_populates="note", cascade="all, delete-orphan")
    suggestions = relationship("CodeSuggestion", back_populates="soap_note", cascade="all, delete-orphan")


class SOAPSection(Base):
    __tablename__ = "soap_sections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soap_note_id: Mapped[int] = mapped_column(ForeignKey("soap_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    section_type: Mapped[SOAPSectionType] = mapped_column(Enum(SOAPSectionType), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    note = relationship("SOAPNote", back_populates="sections")
