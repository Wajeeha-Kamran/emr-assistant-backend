from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.models.session import ConsultationSession
from app.models.soap_note import SOAPNote, SyncStatus
from app.services.emr_sync_client import EMRSyncClient

router = APIRouter()

class SyncStatusResponse(BaseModel):
    sync_status: Optional[SyncStatus]


def _get_owned_note(db: Session, note_id: int, doctor: Doctor) -> SOAPNote:
    """Fetch a note, refusing one that belongs to another doctor.

    Ownership runs through the session, which is what carries doctor_id; the
    note itself has no doctor column. A note belonging to someone else is
    reported as 404 rather than 403, so the API does not confirm that the id
    exists.
    """
    note = (
        db.query(SOAPNote)
        .join(ConsultationSession)
        .filter(
            SOAPNote.id == note_id,
            ConsultationSession.doctor_id == doctor.id
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOAP note not found"
        )
    return note


@router.get("/{note_id}/sync-status", response_model=SyncStatusResponse)
def get_sync_status(
    note_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Report the status of the background sync to the external EMR.

    Signing queues the sync; it does not complete synchronously. Poll here.

    A failed sync leaves the note and its signature intact and leaves the
    session's audio undeleted, so nothing is lost. It does not recover on its
    own: a FAILED note is never re-sent unless POST /{note_id}/retry-sync is
    called.
    """
    note = _get_owned_note(db, note_id, current_doctor)
    return {"sync_status": note.sync_status}


@router.post("/{note_id}/retry-sync", response_model=SyncStatusResponse, status_code=status.HTTP_200_OK)
def retry_sync(
    note_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Re-queue a sync that failed.

    Only a note whose sync_status is FAILED may be retried; anything else
    returns 409. PENDING is refused deliberately — a job already in flight
    would otherwise be duplicated, and the receiving EMR would store the same
    consultation twice.

    EMRSyncClient already makes three attempts with backoff inside a single
    job. This endpoint is for the case where all three were exhausted and the
    job ended. Without it a FAILED note can never reach the EMR, and because
    the retention worker requires sync_status == SUCCESS before deleting audio,
    the consultation recording would also remain on disk indefinitely.

    The note is set back to PENDING and the same background job signing uses is
    queued again. The response reports PENDING, not the outcome; poll
    /{note_id}/sync-status for that.
    """
    note = _get_owned_note(db, note_id, current_doctor)

    if note.sync_status != SyncStatus.FAILED:
        current = note.sync_status.value if note.sync_status else "not set, because the note has not been signed"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a failed sync can be retried. This note's sync status is {current}."
        )

    note.sync_status = SyncStatus.PENDING
    db.commit()
    db.refresh(note)

    background_tasks.add_task(EMRSyncClient.sync_note_to_emr, note.id)

    return {"sync_status": note.sync_status}
