from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import logging

from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.models.soap_note import SOAPNote, SOAPNoteStatus
from app.models.session import ConsultationSession
from app.models.code_suggestion import CodeSuggestion
from app.schemas.code_suggestion import CodeSuggestionResponse, CodeSuggestionUpdateRequest
from app.models.soap_note import GenerationStatus
from app.services.attention_service import AttentionService
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

@router.post("/{note_id}/code-suggestions/generate", response_model=List[CodeSuggestionResponse], status_code=status.HTTP_202_ACCEPTED)
def generate_code_suggestions(
    note_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Start generating ranked ICD-10 and CPT suggestions for a note.

    Diagnosis codes are drawn from the Assessment section and procedure codes
    from the Plan section, matched against the reference code set by clinical
    similarity. Returns five of each, ranked 1 to 10 with no gaps.

    Regenerating replaces the previous suggestions. A signed note returns 409.

    Suggestions are proposals for the clinician to accept, not billing
    decisions.
    
    Returns 202 Accepted. Poll GET to check status.
    """
    note = get_soap_note_or_404(db, note_id, current_doctor)
    
    try:
        CodeSuggesterService.prepare_generation(note.id, db)
        background_tasks.add_task(CodeSuggesterService.generate_in_background, note.id)
        return []
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error preparing code suggestions for note {note_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate code suggestions."
        )

@router.post("/{note_id}/code-suggestions/retry", response_model=List[CodeSuggestionResponse], status_code=status.HTTP_202_ACCEPTED)
def retry_code_suggestions(
    note_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Re-run code suggestion generation for a session whose generation failed or stalled.
    
    Returns 409 if generation is already running. Note that this endpoint can also
    be used if generation is stuck in `processing`.
    """
    note = get_soap_note_or_404(db, note_id, current_doctor)

    # If it's already processing, ensure it's actually stalled before allowing retry.
    if note.codes_generation_status == GenerationStatus.processing:
        if not AttentionService.is_codes_stalled(note):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Code suggestion generation is already in progress"
            )

    try:
        CodeSuggesterService.prepare_generation(note.id, db)
        background_tasks.add_task(CodeSuggesterService.generate_in_background, note.id)
        return []
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

@router.get("/{note_id}/code-suggestions", response_model=List[CodeSuggestionResponse])
def get_code_suggestions(
    note_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Fetch the stored code suggestions for a note, in rank order.

    Each carries an `accepted` flag showing whether the clinician has taken it.
    """
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
    """
    Accept or unaccept a single code suggestion.

    A suggestion belonging to a different note is rejected with 400. Suggestions
    on a signed note cannot be changed and return 409.
    """
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
