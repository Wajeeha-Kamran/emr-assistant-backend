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
    Generate a draft SOAP note from the completed transcript.

    Requires a transcript with status `completed`; otherwise returns 409.

    The pipeline is extractive: every word in the note comes from the transcript,
    nothing is invented. Patient speech becomes Subjective; doctor speech is
    classified sentence by sentence into Objective, Assessment and Plan.
    Questions, greetings and announcements are excluded, since they document
    nothing.

    Regenerating replaces an existing draft and its code suggestions. A signed
    note cannot be regenerated and returns 409.

    **This is a draft for clinical review.** Classification of Assessment in
    particular is known to be weak — diagnostic statements are frequently filed
    under Objective. Clients must present this as editable. See
    docs/module_3_soap_classification.md.
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
    Fetch the SOAP note for a session, with its four sections.

    `status` is DRAFT or SIGNED. A signed note is immutable: edits and
    regenerated suggestions are both rejected.
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
    Edit one section of a draft SOAP note.

    This is the clinician review step the whole system is built around — the
    generated note is a starting point, and this is where it becomes correct.

    Empty content is rejected with 422. A section belonging to a different note
    is rejected with 400. Editing a signed note returns 409: signing is
    deliberately irreversible, because a clinical record that can be altered
    after signature is not a record.
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
