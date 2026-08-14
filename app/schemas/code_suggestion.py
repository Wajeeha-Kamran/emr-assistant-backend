from pydantic import BaseModel, ConfigDict
from app.models.code_reference import CodeType

class CodeSuggestionResponse(BaseModel):
    id: int
    code: str
    description: str
    code_type: CodeType
    rank: int
    confidence_score: float
    accepted: bool

    model_config = ConfigDict(from_attributes=True)

class CodeSuggestionUpdateRequest(BaseModel):
    accepted: bool
