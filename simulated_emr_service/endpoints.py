from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from simulated_emr_service.models import SessionLocal, SimulatedEMRRecord
from datetime import datetime

router = APIRouter()

def get_emr_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SessionMetadata(BaseModel):
    started_at: datetime
    stopped_at: datetime
    duration_seconds: int

class CodeSuggestionPayload(BaseModel):
    code: str
    description: str
    code_type: str
    rank: int
    accepted: bool

class SignaturePayload(BaseModel):
    doctor_id: int
    doctor_name: str
    signed_at: datetime
    method: str

class NoteContent(BaseModel):
    sections: Dict[str, str]
    code_suggestions: List[CodeSuggestionPayload]
    signature: SignaturePayload

class SignedNotePayload(BaseModel):
    source_session_id: int
    source_soap_note_id: int
    session: SessionMetadata
    content: NoteContent

@router.post("/simulated-emr/records", status_code=status.HTTP_201_CREATED)
def receive_record(
    payload: SignedNotePayload,
    db: Session = Depends(get_emr_db)
):
    """
    Receives a finalized SOAP note payload from the EMR Assistant and stores it.
    If the payload does not strictly match the expected SignedNotePayload schema,
    FastAPI will automatically return a 422 Unprocessable Entity.
    """
    record = SimulatedEMRRecord(
        source_session_id=payload.source_session_id,
        source_soap_note_id=payload.source_soap_note_id,
        payload=payload.model_dump(mode='json')
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": "received"}
