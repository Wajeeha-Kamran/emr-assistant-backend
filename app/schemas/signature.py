from pydantic import BaseModel, ConfigDict
from datetime import datetime

class SignatureResponse(BaseModel):
    id: int
    soap_note_id: int
    doctor_id: int
    signed_at: datetime
    method: str

    model_config = ConfigDict(from_attributes=True)
