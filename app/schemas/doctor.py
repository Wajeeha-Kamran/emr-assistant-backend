from pydantic import BaseModel, ConfigDict
from datetime import datetime

class DoctorBase(BaseModel):
    email: str
    full_name: str

class DoctorCreate(DoctorBase):
    password: str

class DoctorResponse(DoctorBase):
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: str | None = None
