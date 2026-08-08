import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.core.security import create_access_token

from app.db.session import SessionLocal

@pytest.fixture
def db():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

@pytest.fixture
def api_test_data(db: Session, client: TestClient):
    """Fixture to set up a doctor, multiple sessions, and transcripts for API testing."""
    doc = Doctor(email="doc_soap_api@example.com", hashed_password="pw", full_name="API Doctor")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # Generate token
    access_token = create_access_token(subject=doc.email)
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 1. Session with completed transcript (ready for generation)
    session_ready = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session_ready)
    db.commit()
    
    t_ready = Transcript(session_id=session_ready.id, status=TranscriptStatus.completed)
    db.add(t_ready)
    db.commit()
    
    # 2. Session with processing transcript (not ready)
    session_processing = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session_processing)
    db.commit()
    
    t_processing = Transcript(session_id=session_processing.id, status=TranscriptStatus.processing)
    db.add(t_processing)
    db.commit()
    
    # 3. Session without a transcript (not ready)
    session_no_transcript = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session_no_transcript)
    db.commit()
    
    # 4. Session with signed SOAP note
    session_signed = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session_signed)
    db.commit()
    
    t_signed = Transcript(session_id=session_signed.id, status=TranscriptStatus.completed)
    db.add(t_signed)
    db.commit()
    
    note = SOAPNote(session_id=session_signed.id, status=SOAPNoteStatus.SIGNED)
    db.add(note)
    db.commit()
    
    # 5. Session belonging to another doctor
    doc_other = Doctor(email="doc_other_api@example.com", hashed_password="pw", full_name="Other Doctor")
    db.add(doc_other)
    db.commit()
    
    session_other = ConsultationSession(doctor_id=doc_other.id, status=SessionStatus.FINALIZED)
    db.add(session_other)
    db.commit()
    
    return {
        "doc": doc,
        "headers": headers,
        "session_ready_id": session_ready.id,
        "session_processing_id": session_processing.id,
        "session_no_transcript_id": session_no_transcript.id,
        "session_signed_id": session_signed.id,
        "session_other_id": session_other.id
    }

def test_generate_draft_success(client: TestClient, api_test_data: dict, db: Session, monkeypatch):
    """POST /generate success returns 201 Created and exactly 4 sections."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_ready_id"]
    
    # Mock SOAPService.generate_draft to avoid slow ML execution
    def mock_generate(*args, **kwargs):
        return {
            "subjective": "Subj",
            "objective": "Obj",
            "assessment": "Ass",
            "plan": "Plan"
        }
    monkeypatch.setattr("app.services.soap_service.SOAPService.generate_draft", mock_generate)
    
    response = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
    assert response.status_code == 201
    
    data = response.json()
    assert data["session_id"] == session_id
    assert data["status"] == "DRAFT"
    assert "sections" in data
    assert len(data["sections"]) == 4
    
    section_types = {s["section_type"] for s in data["sections"]}
    assert section_types == {"SUBJECTIVE", "OBJECTIVE", "ASSESSMENT", "PLAN"}

def test_generate_draft_validation_error(client: TestClient, api_test_data: dict, db: Session, monkeypatch):
    """POST /generate failing 4-section guarantee returns 500."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_ready_id"]
    
    def mock_generate_bad(*args, **kwargs):
        return {
            "subjective": "Subj",
            "objective": "Obj"
            # Missing assessment and plan
        }
    monkeypatch.setattr("app.services.soap_service.SOAPService.generate_draft", mock_generate_bad)
    
    response = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
    assert response.status_code == 500
    assert "missing required sections" in response.json()["detail"].lower()

def test_generate_draft_already_signed(client: TestClient, api_test_data: dict):
    """POST /generate on a SIGNED note returns 409 Conflict."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_signed_id"]
    
    response = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
    assert response.status_code == 409
    assert "signed clinical record" in response.json()["detail"].lower()

def test_generate_draft_transcript_not_ready(client: TestClient, api_test_data: dict):
    """POST /generate with processing or missing transcript returns 409 Conflict."""
    headers = api_test_data["headers"]
    
    # 1. Processing transcript
    res1 = client.post(f"/api/v1/sessions/{api_test_data['session_processing_id']}/soap-notes/generate", headers=headers)
    assert res1.status_code == 409
    assert "not ready" in res1.json()["detail"].lower()
    
    # 2. No transcript
    res2 = client.post(f"/api/v1/sessions/{api_test_data['session_no_transcript_id']}/soap-notes/generate", headers=headers)
    assert res2.status_code == 409
    assert "not ready" in res2.json()["detail"].lower()

def test_generate_draft_unauthorized(client: TestClient, api_test_data: dict):
    """POST /generate on another doctor's session returns 404."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_other_id"]
    
    response = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
    assert response.status_code == 404
    assert "session not found" in response.json()["detail"].lower()

def test_get_soap_note_success(client: TestClient, api_test_data: dict, monkeypatch):
    """GET /soap-notes returns 200 OK and the draft."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_ready_id"]
    
    # Generate draft first
    def mock_generate(*args, **kwargs):
        return {"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"}
    monkeypatch.setattr("app.services.soap_service.SOAPService.generate_draft", mock_generate)
    client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
    
    # Now retrieve it
    response = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["session_id"] == session_id
    assert len(data["sections"]) == 4

def test_get_soap_note_not_found(client: TestClient, api_test_data: dict):
    """GET /soap-notes for session without draft returns 404."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_ready_id"] # Has transcript, but hasn't generated yet
    
    response = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
    assert response.status_code == 404
    assert "draft not found" in response.json()["detail"].lower()

def test_get_soap_note_unauthorized(client: TestClient, api_test_data: dict):
    """GET /soap-notes for another doctor's session returns 404."""
    headers = api_test_data["headers"]
    session_id = api_test_data["session_other_id"]
    
    response = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
    assert response.status_code == 404
    assert "session not found" in response.json()["detail"].lower()
