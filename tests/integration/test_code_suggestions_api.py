import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.models.code_suggestion import CodeSuggestion
from app.models.code_reference import CodeType
from app.core.security import create_access_token
from app.db.session import SessionLocal
from fastapi import status
from unittest.mock import patch

@pytest.fixture
def db():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

@pytest.fixture
def api_setup(db: Session, client: TestClient):
    doc = Doctor(email="test_codesug_api@example.com", hashed_password="pw", full_name="Test Doc")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    other_doc = Doctor(email="test_codesug_api_other@example.com", hashed_password="pw", full_name="Other Doc")
    db.add(other_doc)
    db.commit()
    db.refresh(other_doc)

    token = create_access_token(subject=doc.email)
    other_token = create_access_token(subject=other_doc.email)
    
    return {
        "doc": doc,
        "token": token,
        "other_doc": other_doc,
        "other_token": other_token
    }

def test_generate_code_suggestions_success(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    token = api_setup["token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    
    db.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="I feel pain."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.OBJECTIVE, content="Patient looks okay."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Tension headache."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Rest.")
    ])
    db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 10
    assert data[0]["code_type"] == CodeType.ICD10.value
    assert data[0]["rank"] == 1

def test_get_code_suggestions_success(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    token = api_setup["token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    
    db.add_all([
        CodeSuggestion(soap_note_id=note.id, code="I10", description="Hypertension", code_type=CodeType.ICD10, rank=1, confidence_score=0.9),
        CodeSuggestion(soap_note_id=note.id, code="99213", description="Visit", code_type=CodeType.CPT, rank=2, confidence_score=0.8)
    ])
    db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(f"/api/v1/soap-notes/{note.id}/code-suggestions", headers=headers)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2
    assert data[0]["code"] == "I10"
    assert data[0]["rank"] == 1
    assert data[1]["code"] == "99213"

def test_ownership_denied(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    other_token = api_setup["other_token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    
    headers = {"Authorization": f"Bearer {other_token}"}
    
    response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    
    response = client.get(f"/api/v1/soap-notes/{note.id}/code-suggestions", headers=headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND

def test_generate_code_suggestions_already_signed(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    token = api_setup["token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.SIGNED)
    db.add(note)
    db.commit()
    
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
    
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "signed" in response.json()["detail"].lower()

def test_generate_code_suggestions_empty_note(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    token = api_setup["token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    
    db.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Patient complains of nothing."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.OBJECTIVE, content="Normal."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Not documented in dialogue."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="")
    ])
    db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0

def test_generate_code_suggestions_graceful_degradation(client: TestClient, db: Session, api_setup: dict):
    doc = api_setup["doc"]
    token = api_setup["token"]
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    
    db.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Data"),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.OBJECTIVE, content="Data"),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Data"),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Data")
    ])
    db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    
    with patch("app.api.v1.endpoints.code_suggestions.CodeSuggesterService.generate_suggestions") as mock_generate:
        mock_generate.side_effect = Exception("Model failed to load or similar unexpected issue")
        
        response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        
    response_note = client.get(f"/api/v1/sessions/{session.id}/soap-notes", headers=headers)
    assert response_note.status_code == status.HTTP_200_OK
    assert response_note.json()["id"] == note.id

def test_unauthenticated_access(client: TestClient, db: Session):
    response = client.post("/api/v1/soap-notes/1/code-suggestions/generate")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    response = client.get("/api/v1/soap-notes/1/code-suggestions")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
