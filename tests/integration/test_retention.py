import pytest
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.audio import AudioMetadata
from app.services.session_manager import SessionManager
from app.services.retention_service import RetentionService

@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def test_doctor(db_session):
    doctor = db_session.query(Doctor).filter(Doctor.email == "doc_retention@example.com").first()
    if not doctor:
        doctor = Doctor(email="doc_retention@example.com", full_name="Retention Doc", hashed_password="pwd")
        db_session.add(doctor)
        db_session.commit()
        db_session.refresh(doctor)
    return doctor

def test_cannot_mark_nonexistent_session(db_session):
    with pytest.raises(ValueError) as exc_info:
        RetentionService.mark_audio_for_cleanup(db_session, 99999)
    assert str(exc_info.value) == "Session not found"

def test_cannot_mark_active_session_audio(db_session, test_doctor):
    session = SessionManager.create_session(db_session, test_doctor.id)
    
    # Session is INITIATED
    with pytest.raises(ValueError) as exc_info:
        RetentionService.mark_audio_for_cleanup(db_session, session.id)
    assert "must be FINALIZED" in str(exc_info.value)
    
    # Session is RECORDING
    session = SessionManager.transition_state(db_session, session, SessionStatus.RECORDING)
    with pytest.raises(ValueError) as exc_info:
        RetentionService.mark_audio_for_cleanup(db_session, session.id)
    assert "must be FINALIZED" in str(exc_info.value)

    # Session is STOPPED
    session = SessionManager.transition_state(db_session, session, SessionStatus.STOPPED)
    with pytest.raises(ValueError) as exc_info:
        RetentionService.mark_audio_for_cleanup(db_session, session.id)
    assert "must be FINALIZED" in str(exc_info.value)

def test_mark_finalized_session_audio_success(db_session, test_doctor):
    session = SessionManager.create_session(db_session, test_doctor.id)
    
    # Add dummy audio metadata
    audio = AudioMetadata(
        session_id=session.id,
        file_path="./storage/test_audio/test_retention.wav",
        duration_seconds=120.5,
        format="audio/wav"
    )
    db_session.add(audio)
    db_session.commit()
    db_session.refresh(audio)
    
    # Transition sequentially: INITIATED -> RECORDING -> STOPPED -> FINALIZED
    session = SessionManager.transition_state(db_session, session, SessionStatus.RECORDING)
    session = SessionManager.transition_state(db_session, session, SessionStatus.STOPPED)
    session = SessionManager.transition_state(db_session, session, SessionStatus.FINALIZED)
    
    # Mark for cleanup
    updated_audio = RetentionService.mark_audio_for_cleanup(db_session, session.id)
    
    assert updated_audio is not None
    assert updated_audio.retention_marked_for_deletion_at is not None
    assert updated_audio.deleted_at is None

def test_no_audio_metadata_returns_none(db_session, test_doctor):
    session = SessionManager.create_session(db_session, test_doctor.id)
    
    # Transition sequentially to FINALIZED without adding audio metadata
    session = SessionManager.transition_state(db_session, session, SessionStatus.RECORDING)
    session = SessionManager.transition_state(db_session, session, SessionStatus.STOPPED)
    session = SessionManager.transition_state(db_session, session, SessionStatus.FINALIZED)
    
    result = RetentionService.mark_audio_for_cleanup(db_session, session.id)
    assert result is None
