from fastapi import APIRouter, Depends, status, HTTPException, File, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import get_current_doctor
from app.db.session import get_db
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.schemas.session import SessionResponse
from app.services.session_manager import SessionManager
from app.services.audio_manager import AudioManager

router = APIRouter()

@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # No request body is accepted. The doctor_id is strictly sourced from the JWT.
    session = SessionManager.create_session(db=db, doctor_id=current_doctor.id)
    return session

@router.post("/{session_id}/start-recording", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def start_recording(
    session_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
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
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
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
        db.commit()
        db.refresh(session)
        
    except ValueError as e:
        db.rollback()
        error_msg = str(e)
        if "maximum allowed duration" in error_msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        
    return session
