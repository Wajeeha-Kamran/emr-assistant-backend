import pytest
from app.models.session import SessionStatus
from app.services.session_manager import SessionManager
from app.db.session import SessionLocal

def test_create_session(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "doc_session@example.com", "full_name": "Session Doc", "password": "pwd"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "doc_session@example.com", "password": "pwd"}
    )
    token = login_resp.json()["access_token"]
    
    response = client.post(
        "/api/v1/sessions/",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["status"] == "INITIATED"
    
    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    doctor_id = me_resp.json()["id"]
    assert data["doctor_id"] == doctor_id

def test_create_session_unauthorized(client):
    response = client.post("/api/v1/sessions/")
    assert response.status_code == 401

def test_session_state_transitions(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "doc_state@example.com", "full_name": "State Doc", "password": "pwd"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "doc_state@example.com", "password": "pwd"}
    )
    token = login_resp.json()["access_token"]
    
    create_resp = client.post(
        "/api/v1/sessions/",
        headers={"Authorization": f"Bearer {token}"}
    )
    session_id = create_resp.json()["id"]
    
    db = SessionLocal()
    from app.models.session import ConsultationSession
    session = db.query(ConsultationSession).filter(ConsultationSession.id == session_id).first()
    
    SessionManager.transition_state(db, session, SessionStatus.RECORDING)
    assert session.status == SessionStatus.RECORDING
    assert session.started_at is not None
    
    with pytest.raises(ValueError) as exc:
        SessionManager.transition_state(db, session, SessionStatus.FINALIZED)
    assert "Illegal state transition" in str(exc.value)
    
    SessionManager.transition_state(db, session, SessionStatus.STOPPED)
    assert session.status == SessionStatus.STOPPED
    
    SessionManager.transition_state(db, session, SessionStatus.FINALIZED)
    assert session.status == SessionStatus.FINALIZED
    db.close()
