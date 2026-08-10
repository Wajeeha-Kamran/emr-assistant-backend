from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.models.session import ConsultationSession
from app.models.soap_note import SOAPNote
from app.schemas.soap_note import SOAPNoteResponse, SOAPSectionUpdateRequest
from app.services.soap_note_service import SOAPNoteService
from app.services.exceptions import SessionNotFoundError, SOAPValidationError, SOAPNoteAlreadySignedError, TranscriptNotReadyError, SOAPSectionNotFoundError

router = APIRouter()
note_router = APIRouter()

@router.post("/{session_id}/soap-notes/generate", response_model=SOAPNoteResponse, status_code=status.HTTP_201_CREATED)
def generate_soap_note_draft(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Doctor = Depends(get_current_doctor)
):
    """
    Generates a new SOAP note draft for the given session.
    """
    try:
        soap_note = SOAPNoteService.generate_and_save_draft(db, session_id, current_user.id)
        return soap_note
    except SessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TranscriptNotReadyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except SOAPValidationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{session_id}/soap-notes", response_model=SOAPNoteResponse)
def get_soap_note(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Doctor = Depends(get_current_doctor)
):
    """
    Retrieves the current SOAP note for the given session.
    """
    # 1. Verify ownership of the session
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # 2. Retrieve SOAP Note
    soap_note = db.query(SOAPNote).filter(SOAPNote.session_id == session_id).first()
    if not soap_note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOAP note draft not found for this session")

    return soap_note

@note_router.patch("/{note_id}/sections/{section_id}", response_model=SOAPNoteResponse)
def update_soap_section(
    note_id: int,
    section_id: int,
    request: SOAPSectionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Doctor = Depends(get_current_doctor)
):
    """
    Updates a specific section of a SOAP note.
    """
    note = (
        db.query(SOAPNote)
        .join(ConsultationSession)
        .filter(
            SOAPNote.id == note_id,
            ConsultationSession.doctor_id == current_user.id
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOAP note not found"
        )
        
    try:
        updated_note = SOAPNoteService.update_section(db, note_id, section_id, request.content)
        return updated_note
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except SOAPSectionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
