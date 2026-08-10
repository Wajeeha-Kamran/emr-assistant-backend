from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.db.base import Base
from app.models.code_reference import CodeType

class CodeSuggestion(Base):
    __tablename__ = "code_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    soap_note_id: Mapped[int] = mapped_column(ForeignKey("soap_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    code_type: Mapped[CodeType] = mapped_column(SQLAlchemyEnum(CodeType), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    soap_note = relationship("SOAPNote", back_populates="suggestions")
