import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
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
def signature_api_data(db: Session, client: TestClient):
    doc = Doctor(email="doc_sign_api@example.com", hashed_password="pw", full_name="Sign Doc")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    other_doc = Doctor(email="doc_sign_api_other@example.com", hashed_password="pw", full_name="Other Doc")
    db.add(other_doc)
    db.commit()
    db.refresh(other_doc)
    
    token = create_access_token(subject=doc.email)
    other_token = create_access_token(subject=other_doc.email)
    
    session1 = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session1)
    db.commit()
    
    note_draft = SOAPNote(session_id=session1.id, status=SOAPNoteStatus.DRAFT)
    db.add(note_draft)
    db.commit()
    
    sec1 = SOAPSection(soap_note_id=note_draft.id, section_type=SOAPSectionType.SUBJECTIVE, content="Sub")
    sec2 = SOAPSection(soap_note_id=note_draft.id, section_type=SOAPSectionType.OBJECTIVE, content="Obj")
    sec3 = SOAPSection(soap_note_id=note_draft.id, section_type=SOAPSectionType.ASSESSMENT, content="Ass")
    sec4 = SOAPSection(soap_note_id=note_draft.id, section_type=SOAPSectionType.PLAN, content="Plan")
    db.add_all([sec1, sec2, sec3, sec4])
    db.commit()
    
    session2 = ConsultationSession(doctor_id=other_doc.id, status=SessionStatus.FINALIZED)
    db.add(session2)
    db.commit()
    
    note_other = SOAPNote(session_id=session2.id, status=SOAPNoteStatus.DRAFT)
    db.add(note_other)
    db.commit()
    
    return {
        "doc": doc,
        "token": token,
        "other_token": other_token,
        "note_draft": note_draft,
        "sec_draft": sec1,
        "note_other": note_other
    }

def test_sign_note_success(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    doc = signature_api_data["doc"]
    headers = {"Authorization": f"Bearer {signature_api_data['token']}"}
    
    response = client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    assert response.status_code == 201
    data = response.json()
    
    assert data["soap_note_id"] == note.id
    assert data["doctor_id"] == doc.id
    assert data["method"] == "CONFIRMATION"
    assert "signed_at" in data
    assert data["signed_at"] is not None
    
    # Ensure note status is updated
    get_response = client.get(f"/api/v1/sessions/{note.session_id}/soap-notes", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "SIGNED"

def test_sign_note_double_sign_rejected(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    headers = {"Authorization": f"Bearer {signature_api_data['token']}"}
    
    response = client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    assert response.status_code == 201
    
    # Try again
    response2 = client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    assert response2.status_code == 409
    assert "signed" in response2.json()["detail"].lower()

def test_sign_note_ownership_denied(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    # Trying to sign note_draft using other_token
    headers = {"Authorization": f"Bearer {signature_api_data['other_token']}"}
    
    response = client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_sign_note_unauthenticated(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    response = client.post(f"/api/v1/soap-notes/{note.id}/sign")
    assert response.status_code == 401

def test_immutability_edit_after_sign_rejected(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    sec = signature_api_data["sec_draft"]
    headers = {"Authorization": f"Bearer {signature_api_data['token']}"}
    
    # Sign it
    client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    
    # Try editing
    payload = {"content": "new text"}
    response = client.patch(f"/api/v1/soap-notes/{note.id}/sections/{sec.id}", json=payload, headers=headers)
    assert response.status_code == 409
    assert "signed" in response.json()["detail"].lower()

def test_immutability_suggestions_after_sign_rejected(client: TestClient, signature_api_data: dict):
    note = signature_api_data["note_draft"]
    headers = {"Authorization": f"Bearer {signature_api_data['token']}"}
    
    # Sign it
    client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
    
    # Try generating code suggestions
    response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
    assert response.status_code == 409
    assert "signed" in response.json()["detail"].lower()
