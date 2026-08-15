from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_doctor
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.transcript import TranscriptResponse
from app.services.asr_service import ASRService

router = APIRouter()

@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
def get_transcript(
    session_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Fetch the transcript, with each segment labelled DOCTOR or PATIENT.

    **Poll this endpoint.** `status` is `processing` until transcription
    finishes, then `completed`, or `failed` if it did not. A SOAP note cannot be
    generated until the status is `completed`.

    Segments are returned in chronological order.

    Speaker labels are produced by a diarization pipeline whose accuracy has been
    measured rather than assumed: it meets its target when the two voices are
    acoustically distinguishable and speak at a conversational pace, and degrades
    when the voices are similar or turn-taking is rapid. Clients should treat
    speaker labels as correctable by the clinician, not as ground truth. See
    docs/module_9_1_accuracy.md.
    """
    # Ownership verification
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_doctor.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or does not belong to the current doctor"
        )
        
    transcript = db.query(Transcript).filter(Transcript.session_id == session_id).first()
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found for this session"
        )
        
    return transcript

@router.post("/{session_id}/transcript/retry")
def retry_transcription(
    session_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Re-run transcription for a session whose transcript failed.

    Resets the transcript to `processing` and starts the pipeline again, so any
    previously produced segments are replaced.

    Returns 409 if transcription is already running — the guard prevents two
    passes writing segments for the same session at once. Note that calling this
    on a transcript that already completed will discard it and start over.
    """
    # Ownership verification
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_doctor.id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or does not belong to the current doctor"
        )
        
    # State check: must be STOPPED
    if session.status != SessionStatus.STOPPED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription can only be retried when session is STOPPED"
        )
        
    transcript = db.query(Transcript).filter(Transcript.session_id == session_id).first()
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript record does not exist for this session"
        )
        
    # Concurrency check
    if transcript.status == TranscriptStatus.processing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcription is already in progress"
        )
        
    # Reset status to processing.
    #
    # finalized_at must be cleared alongside it. Found during the Module 9.2
    # manual API run on 15 Aug 2026: after a retry, GET .../transcript returned
    # status "processing" while still carrying the completion timestamp from the
    # previous attempt. A client would render "completed at 01:52" beside a
    # spinner. Any field describing the outcome of a run is stale the moment a
    # new run starts.
    transcript.status = TranscriptStatus.processing
    transcript.finalized_at = None
    db.commit()
    
    background_tasks.add_task(ASRService.transcribe_and_diarize, session_id)
    
    return {"status": "processing", "message": "ASR transcription task restarted"}
