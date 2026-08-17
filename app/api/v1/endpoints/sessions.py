from fastapi import APIRouter, Depends, status, HTTPException, File, UploadFile, BackgroundTasks
from sqlalchemy.orm import Session
from app.api.deps import get_current_doctor
from app.db.session import get_db
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.session import SessionResponse
from app.services.session_manager import SessionManager
from app.services.audio_manager import AudioManager
from app.services.asr_service import ASRService

router = APIRouter()

@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Create a consultation session.

    The session is the container everything else attaches to: the audio, the
    transcript, the SOAP note, the signature and the sync record. It starts in
    CREATED and must be started before audio can be uploaded.
    """
    # No request body is accepted. The doctor_id is strictly sourced from the JWT.
    session = SessionManager.create_session(db=db, doctor_id=current_doctor.id)
    return session

@router.post("/{session_id}/start-recording", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def start_recording(
    session_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Move the session into RECORDING.

    Call this when the doctor begins recording, before any audio is uploaded.
    A session already recording returns 409 — the state machine does not allow
    a second start, which prevents one consultation being recorded twice over.

    A session belonging to another doctor returns 404 rather than 403, so the
    API does not reveal that it exists.
    """
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_doctor.id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or does not belong to the current doctor"
        )
    
    try:
        session = SessionManager.transition_state(db, session, SessionStatus.RECORDING)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    
    return session

@router.post("/{session_id}/stop-recording", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def stop_recording(
    session_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Upload the consultation audio and end the recording.

    Accepts a multipart file. Common audio and video container types are
    accepted, including all the MIME spellings of WAV that clients use in
    practice — Windows reports `audio/wave` where browsers send `audio/wav`.

    Returns as soon as the file is stored and validated. **Transcription then
    runs in the background** and takes roughly as long as the recording itself
    on CPU, so do not expect a transcript immediately; poll the transcript
    endpoint.

    Recordings longer than the configured maximum are rejected with 400.
    """
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_doctor.id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or does not belong to the current doctor"
        )
        
    try:
        session = SessionManager.transition_state(db, session, SessionStatus.STOPPED, commit=False)
        audio_metadata = AudioManager.save_and_validate_audio(session_id, file)
        
        db.add(audio_metadata)
        
        # Initialize the transcript in 'processing' status
        transcript = Transcript(session_id=session_id, status=TranscriptStatus.processing)
        db.add(transcript)
        
        db.commit()
        db.refresh(session)
        
        # Trigger background processing task
        background_tasks.add_task(ASRService.transcribe_and_diarize, session_id)
        
    except ValueError as e:
        db.rollback()
        error_msg = str(e)
        if "maximum allowed duration" in error_msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        
    return session


@router.post("/{session_id}/discard", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def discard_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Abandon a consultation that never produced a recording.

    The client creates a session and calls start-recording the moment the doctor
    presses Start, so the server knows a consultation is under way. If the
    doctor then backs out, that session would otherwise sit in RECORDING
    forever: it is not reported by the attention list, because with no audio and
    no transcript there is nothing to resume and nothing on disk to clean up.
    This endpoint closes it.

    Allowed only from INITIATED or RECORDING. Once stop-recording has run, the
    audio exists and the consultation holds clinical content; recovering it
    through the attention list is then the only correct path, and 409 is
    returned here. A doctor cannot discard a recorded consultation.

    The row is kept rather than deleted, with discarded_at set. An abandoned
    consultation holds no clinical content, but the fact that one was started
    and abandoned is itself something an audit would want to see.
    """
    session = db.query(ConsultationSession).filter(
        ConsultationSession.id == session_id,
        ConsultationSession.doctor_id == current_doctor.id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or does not belong to the current doctor"
        )

    try:
        session = SessionManager.transition_state(db, session, SessionStatus.DISCARDED)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A consultation in {session.status.value} cannot be discarded. "
                "Once the recording has been uploaded the consultation holds "
                "clinical content and must be completed rather than abandoned."
            )
        )

    return session
