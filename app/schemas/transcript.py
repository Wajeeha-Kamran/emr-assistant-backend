from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional
from app.models.transcript import TranscriptStatus

class TranscriptSegmentResponse(BaseModel):
    id: int
    speaker_role: str
    text: str
    start_time: Optional[float]
    end_time: Optional[float]

    model_config = ConfigDict(from_attributes=True)

class TranscriptResponse(BaseModel):
    id: int
    session_id: int
    status: TranscriptStatus
    created_at: datetime
    finalized_at: Optional[datetime]
    segments: List[TranscriptSegmentResponse]

    model_config = ConfigDict(from_attributes=True)
