import os
import io
import pytest
from fastapi import status
from app.models.session import SessionStatus
from app.models.transcript import TranscriptStatus

# Helper to register and login a test doctor
def get_auth_headers(client, email="doc_transcripts@example.com"):
    # Register
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepassword", "full_name": "Test Transcripts"}
    )
    # Login
    response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "securepassword"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def mock_pipeline(monkeypatch):
    # Mock ASRService.transcribe_audio to avoid running the real Whisper engine
    from app.services.asr_service import ASRService
    from app.services.diarization_service import DiarizationService
    
    def mock_transcribe(audio_path):
        return {
            "text": "Hello doctor. Hi patient.",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Hello doctor."},
                {"start": 4.0, "end": 6.0, "text": "Hi patient."}
            ]
        }
        
    def mock_diarize(segments):
        return [
            {"start": 0.0, "end": 2.0, "text": "Hello doctor.", "speaker_role": "DOCTOR"},
            {"start": 4.0, "end": 6.0, "text": "Hi patient.", "speaker_role": "PATIENT"}
        ]
        
    monkeypatch.setattr(ASRService, "transcribe_audio", mock_transcribe)
    monkeypatch.setattr(DiarizationService, "diarize_segments", mock_diarize)

def test_transcription_triggered_automatically(client, mock_pipeline):
    headers = get_auth_headers(client, "doc_auto@example.com")
    
    # 1. Create session
    resp = client.post("/api/v1/sessions/", headers=headers)
    session_id = resp.json()["id"]
    
    # 2. Start recording
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)
    
    # 3. Stop recording (uploads audio file & triggers bg task)
    dummy_wav = io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    dummy_wav.name = "test.wav"
    stop_resp = client.post(
        f"/api/v1/sessions/{session_id}/stop-recording",
        files={"file": ("test.wav", dummy_wav, "audio/wav")},
        headers=headers
    )
    assert stop_resp.status_code == status.HTTP_200_OK
    assert stop_resp.json()["status"] == SessionStatus.STOPPED
    
    # 4. Fetch transcript -> TestClient executes BackgroundTasks synchronously,
    # so the status is already updated to completed.
    transcript_resp = client.get(f"/api/v1/sessions/{session_id}/transcript", headers=headers)
    assert transcript_resp.status_code == status.HTTP_200_OK
    data = transcript_resp.json()
    assert data["status"] == TranscriptStatus.completed
    assert len(data["segments"]) == 2
    assert data["segments"][0]["speaker_role"] == "DOCTOR"
    assert data["segments"][1]["speaker_role"] == "PATIENT"

def test_get_transcript_ownership(client):
    headers_owner = get_auth_headers(client, "owner@example.com")
    headers_other = get_auth_headers(client, "other@example.com")
    
    # Create session as owner
    resp = client.post("/api/v1/sessions/", headers=headers_owner)
    session_id = resp.json()["id"]
    
    # Fetch transcript as other -> 404
    resp = client.get(f"/api/v1/sessions/{session_id}/transcript", headers=headers_other)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

def test_retry_concurrency_guard(client, mock_pipeline):
    headers = get_auth_headers(client, "concurrency@example.com")
    
    # Create session and stop recording to create a transcript
    resp = client.post("/api/v1/sessions/", headers=headers)
    session_id = resp.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)
    
    dummy_wav = io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    dummy_wav.name = "test.wav"
    client.post(
        f"/api/v1/sessions/{session_id}/stop-recording",
        files={"file": ("test.wav", dummy_wav, "audio/wav")},
        headers=headers
    )
    
    # Direct DB modification to set status to 'processing' to test guard
    from app.db.session import SessionLocal
    from app.models.transcript import Transcript
    db = SessionLocal()
    t = db.query(Transcript).filter(Transcript.session_id == session_id).first()
    t.status = TranscriptStatus.processing
    db.commit()
    db.close()
    
    # Hitting retry while processing -> should get 409 Conflict
    retry_resp = client.post(f"/api/v1/sessions/{session_id}/transcript/retry", headers=headers)
    assert retry_resp.status_code == status.HTTP_409_CONFLICT
    assert "already in progress" in retry_resp.json()["detail"]

def test_retry_success(client, mock_pipeline):
    headers = get_auth_headers(client, "retry@example.com")
    
    # Create session and stop recording to create a transcript
    resp = client.post("/api/v1/sessions/", headers=headers)
    session_id = resp.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)
    
    dummy_wav = io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\x3e\x00\x00\x00\x7d\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    dummy_wav.name = "test.wav"
    client.post(
        f"/api/v1/sessions/{session_id}/stop-recording",
        files={"file": ("test.wav", dummy_wav, "audio/wav")},
        headers=headers
    )
    
    # Set status to failed first to simulate error recovery
    from app.db.session import SessionLocal
    from app.models.transcript import Transcript
    db = SessionLocal()
    t = db.query(Transcript).filter(Transcript.session_id == session_id).first()
    t.status = TranscriptStatus.failed
    db.commit()
    db.close()
    
    # Hit retry
    retry_resp = client.post(f"/api/v1/sessions/{session_id}/transcript/retry", headers=headers)
    assert retry_resp.status_code == status.HTTP_200_OK
    assert retry_resp.json()["status"] == "processing"
