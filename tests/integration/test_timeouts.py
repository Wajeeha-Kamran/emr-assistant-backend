import time
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from concurrent.futures import TimeoutError as FuturesTimeoutError
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptStatus, TranscriptSegment
from app.core.security import create_access_token

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def auth_headers(db):
    doc = db.query(Doctor).first()
    if not doc:
        doc = Doctor(email="timeout@example.com", full_name="Dr. Timeout", hashed_password="hashed")
        db.add(doc)
        db.commit()
    token = create_access_token(doc.email)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def active_session_with_transcript(db, auth_headers):
    doc = db.query(Doctor).first()
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.STOPPED)
    db.add(session)
    db.commit()
    db.refresh(session)
    
    transcript = Transcript(session_id=session.id, status=TranscriptStatus.completed)
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    
    seg = TranscriptSegment(transcript_id=transcript.id, speaker_role="DOCTOR", text="Some test text.", start_time=0.0, end_time=1.0)
    db.add(seg)
    db.commit()
    
    return session.id

def test_genuine_error_surfaces_within_5_seconds_for_nlp_timeout(auth_headers, active_session_with_transcript):
    """
    Asserts that a genuine ERROR response returns to the caller within the 5-second 
    robustness budget when the NLP engine times out. 
    
    NOTE: This does NOT test that processing completes in 5 seconds. It tests that 
    the system correctly cuts off a runaway process (mocked to sleep forever) and 
    returns a 503 error to the client before 5 seconds have elapsed.
    """
    client = TestClient(app)
    
    from unittest.mock import patch, MagicMock
    def mock_sleep_forever(*args, **kwargs):
        time.sleep(10)
        return {"subjective": [], "objective": [], "assessment": [], "plan": []}

    mock_engine = MagicMock()
    mock_engine.classify_doctor_segments.side_effect = mock_sleep_forever

    # Patch get_instance so we don't load the real model (which takes >5s to download/load)
    with patch("app.services.soap_service.ClinicalBERTEngine.get_instance", return_value=mock_engine):
        with patch("app.core.config.settings.NLP_TIMEOUT_SECONDS", new=2):
            start_time = time.time()
            response = client.post(f"/api/v1/sessions/{active_session_with_transcript}/soap-notes/generate", headers=auth_headers)
            elapsed_time = time.time() - start_time
            
            assert response.status_code == 503
            assert response.json()["detail"] == "NLP Engine Timeout"
            assert elapsed_time < 5.0, f"Error did not surface within 5 seconds! Took {elapsed_time}s"

def test_dynamic_asr_timeout_logic(db):
    """
    Asserts that the ASR timeout correctly scales proportionally with audio duration,
    and respects the floor value.
    """
    from app.services.asr_service import ASRService
    from app.models.audio import AudioMetadata
    from app.models.transcript import Transcript
    from unittest.mock import patch, MagicMock
    import concurrent.futures

    # We will test two scenarios: short audio (uses floor) and long audio (uses factor)
    # Since it runs in a background task, we patch ThreadPoolExecutor and engine.transcribe
    # to avoid real work, we just want to assert the `timeout` value passed to `future.result(timeout=...)`
    
    from app.models.doctor import Doctor
    from app.models.session import ConsultationSession
    doc = db.query(Doctor).first()
    if not doc:
        doc = Doctor(email="dummy@test.com", full_name="Dummy", hashed_password="pw")
        db.add(doc)
        db.commit()
        
    for duration, expected_timeout in [(10.0, 300), (60.0, 360)]:
        session = ConsultationSession(doctor_id=doc.id)
        db.add(session)
        db.commit()
        session_id = session.id
        
        audio = AudioMetadata(session_id=session_id, file_path="dummy.wav", duration_seconds=duration, format="wav")
        db.add(audio)
        
        transcript = Transcript(session_id=session_id)
        db.add(transcript)
        db.commit()

        # Mock future to track what timeout it was called with
        mock_future = MagicMock()
        
        def mock_submit(*args, **kwargs):
            return mock_future

        with patch("concurrent.futures.ThreadPoolExecutor.submit", side_effect=mock_submit):
            with patch("app.services.diarization_service.DiarizationService.diarize_segments", return_value=[]):
                # The service handles errors, so even if mock_future.result() returns MagicMock it won't crash
                # actually it expects a dict, so let's make it return a dict
                mock_future.result.return_value = {"text": "hello", "segments": []}
                
                ASRService.transcribe_and_diarize(session_id)
                
                # Assert future.result was called with the correct dynamic timeout
                mock_future.result.assert_called_with(timeout=expected_timeout)

        # Cleanup
        db.delete(audio)
        db.delete(transcript)
        db.commit()

