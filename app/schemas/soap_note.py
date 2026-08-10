from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from app.models.soap_note import SOAPNoteStatus, SOAPSectionType

class SOAPSectionResponse(BaseModel):
    id: int
    section_type: SOAPSectionType
    content: str

    model_config = ConfigDict(from_attributes=True)

class SOAPNoteResponse(BaseModel):
    id: int
    session_id: int
    status: SOAPNoteStatus
    created_at: datetime
    last_edited_at: Optional[datetime] = None
    sections: List[SOAPSectionResponse]

    model_config = ConfigDict(from_attributes=True)

from pydantic import field_validator

class SOAPSectionUpdateRequest(BaseModel):
    content: str
    
    @field_validator('content')
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content cannot be empty or just whitespace")
        return v
