from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.models.session import ConsultationSession
from app.models.soap_note import SOAPNote
from app.schemas.signature import SignatureResponse
from app.services.note_finalizer import NoteFinalizerService
from app.services.exceptions import SOAPNoteAlreadySignedError

router = APIRouter()

@router.post("/{note_id}/sign", response_model=SignatureResponse, status_code=status.HTTP_201_CREATED)
def sign_soap_note(
    note_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Doctor = Depends(get_current_doctor)
):
    """
    Sign the note. This is the irreversible step.

    Signing does three things: it locks the note against further edits, it marks
    the session finalised so its audio becomes eligible for deletion, and it
    triggers a background sync to the external EMR.

    A note can only be signed once; a second attempt returns 409.

    Clients should treat this as a deliberate action requiring confirmation. Up
    to this point everything the system produced was a draft under review; after
    it, the note is a clinical record.
    """
    # 1. Ownership and existence check
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
        signature = NoteFinalizerService.sign_note(db, note_id, current_user.id, background_tasks)
        return signature
    except SOAPNoteAlreadySignedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
