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
        
    # Reset status to processing
    transcript.status = TranscriptStatus.processing
    db.commit()
    
    background_tasks.add_task(ASRService.transcribe_and_diarize, session_id)
    
    return {"status": "processing", "message": "ASR transcription task restarted"}
