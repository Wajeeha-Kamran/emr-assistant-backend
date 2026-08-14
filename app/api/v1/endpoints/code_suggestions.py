from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import logging

from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.models.soap_note import SOAPNote, SOAPNoteStatus
from app.models.session import ConsultationSession
from app.models.code_suggestion import CodeSuggestion
from app.schemas.code_suggestion import CodeSuggestionResponse, CodeSuggestionUpdateRequest
from app.services.code_suggester import CodeSuggesterService, SOAPNoteAlreadySignedError

logger = logging.getLogger(__name__)

router = APIRouter()

def get_soap_note_or_404(db: Session, note_id: int, current_doctor: Doctor) -> SOAPNote:
    note = (
        db.query(SOAPNote)
        .join(ConsultationSession)
        .filter(
            SOAPNote.id == note_id,
            ConsultationSession.doctor_id == current_doctor.id
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOAP note not found"
        )
    return note

@router.post("/{note_id}/code-suggestions/generate", response_model=List[CodeSuggestionResponse])
def generate_code_suggestions(
    note_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    note = get_soap_note_or_404(db, note_id, current_doctor)
    
    try:
        suggestions = CodeSuggesterService.generate_suggestions(note.id, db)
        return suggestions
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error generating code suggestions for note {note_id}: {e}", exc_info=True)
        # Returning a 500 error here. This does not affect the SOAP note itself,
        # which means the graceful degradation requirement is met. The client will handle this error
        # while still being able to fetch the SOAP note from the GET /soap-notes/{id} endpoint.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate code suggestions."
        )

@router.get("/{note_id}/code-suggestions", response_model=List[CodeSuggestionResponse])
def get_code_suggestions(
    note_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    # Verify ownership before returning suggestions
    get_soap_note_or_404(db, note_id, current_doctor)
    
    suggestions = (
        db.query(CodeSuggestion)
        .filter(CodeSuggestion.soap_note_id == note_id)
        .order_by(CodeSuggestion.rank.asc())
        .all()
    )
    
    return suggestions

@router.patch("/{note_id}/code-suggestions/{suggestion_id}", response_model=CodeSuggestionResponse)
def update_code_suggestion(
    note_id: int,
    suggestion_id: int,
    request: CodeSuggestionUpdateRequest,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    note = get_soap_note_or_404(db, note_id, current_doctor)
    
    if note.status == SOAPNoteStatus.SIGNED:
        # Note: We throw a 409 here to match existing behavior for signed notes
        # but the request was actually to modify a signed note so 409 is correct.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify code suggestions on a signed SOAP note."
        )
        
    suggestion = db.query(CodeSuggestion).filter(
        CodeSuggestion.id == suggestion_id,
        CodeSuggestion.soap_note_id == note.id
    ).first()
    
    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Code suggestion not found or does not belong to this note."
        )
        
    suggestion.accepted = request.accepted
    db.commit()
    db.refresh(suggestion)
    
    return suggestion
