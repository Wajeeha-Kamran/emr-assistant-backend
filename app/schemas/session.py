from pydantic import BaseModel, ConfigDict
from datetime import datetime
from app.models.session import SessionStatus

class SessionResponse(BaseModel):
    id: int
    doctor_id: int
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    finalized_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
