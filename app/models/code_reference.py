from enum import Enum
from sqlalchemy import Column, String, Text, Enum as SQLAlchemyEnum
from app.db.base import Base

class CodeType(str, Enum):
    ICD10 = "ICD10"
    CPT = "CPT"

class CodeReference(Base):
    __tablename__ = "code_reference"

    code = Column(String(50), primary_key=True, index=True)
    description = Column(Text, nullable=False)
    code_type = Column(SQLAlchemyEnum(CodeType), nullable=False, index=True)
