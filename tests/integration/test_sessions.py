import pytest
from app.models.session import SessionStatus
from app.services.session_manager import SessionManager
from app.db.session import SessionLocal

def test_create_session(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "doc_session@example.com", "full_name": "Session Doc", "password": "testpassword"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "doc_session@example.com", "password": "testpassword"}
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
        json={"email": "doc_state@example.com", "full_name": "State Doc", "password": "testpassword"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "doc_state@example.com", "password": "testpassword"}
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

def test_start_recording(client):
    client.post("/api/v1/auth/register", json={"email": "doc_start_rec@example.com", "full_name": "Start Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_start_rec@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    
    start_resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "RECORDING"
    assert start_resp.json()["started_at"] is not None

def test_start_recording_conflict(client):
    client.post("/api/v1/auth/register", json={"email": "doc_start_rec@example.com", "full_name": "Start Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_start_rec@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    
    start_resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    assert start_resp.status_code == 200
    
    conflict_resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    assert conflict_resp.status_code == 409
    assert "Illegal state transition" in conflict_resp.json()["detail"]

def test_start_recording_ownership(client):
    client.post("/api/v1/auth/register", json={"email": "doc_other@example.com", "full_name": "Other Doc", "password": "testpassword"})
    login_other = client.post("/api/v1/auth/login", data={"username": "doc_other@example.com", "password": "testpassword"})
    token_other = login_other.json()["access_token"]
    
    client.post("/api/v1/auth/register", json={"email": "doc_start_rec@example.com", "full_name": "Start Doc", "password": "testpassword"})
    login_start = client.post("/api/v1/auth/login", data={"username": "doc_start_rec@example.com", "password": "testpassword"})
    token_start = login_start.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token_start}"})
    session_id = create_resp.json()["id"]
    
    not_found_resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token_other}"})
    assert not_found_resp.status_code == 404


# ---------------------------------------------------------------------------
# Discarding an abandoned consultation
#
# Added 17 Aug 2026. The client creates the session and calls start-recording
# when the doctor presses Start, so the server observes UC-01 as it happens.
# The cost is a state nothing previously closed: a consultation begun and then
# abandoned before any audio was uploaded. It is not reported by the attention
# list — with no audio and no transcript there is nothing to resume — so
# without this endpoint it would sit in RECORDING forever.
# ---------------------------------------------------------------------------

def _discard_auth(client, email):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Discard Doc", "password": "testpassword"}
    )
    login = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "testpassword"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_discard_an_initiated_session(client):
    headers = _discard_auth(client, "discard_init@example.com")
    session_id = client.post("/api/v1/sessions/", headers=headers).json()["id"]

    response = client.post(f"/api/v1/sessions/{session_id}/discard", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "DISCARDED"


def test_discard_a_recording_session(client):
    """The real case: the doctor pressed Start, then backed out."""
    headers = _discard_auth(client, "discard_rec@example.com")
    session_id = client.post("/api/v1/sessions/", headers=headers).json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)

    response = client.post(f"/api/v1/sessions/{session_id}/discard", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "DISCARDED"

    from app.models.session import ConsultationSession
    db = SessionLocal()
    try:
        stored = db.query(ConsultationSession).filter(
            ConsultationSession.id == session_id
        ).first()
        # Kept, not deleted, and stamped.
        assert stored is not None
        assert stored.status == SessionStatus.DISCARDED
        assert stored.discarded_at is not None
    finally:
        db.close()


def test_discard_refused_once_audio_exists(client):
    """
    A recorded consultation holds clinical content and must be completed or
    recovered, never abandoned. Reaching STOPPED requires an upload, so the
    state is set directly here rather than uploading a file.
    """
    headers = _discard_auth(client, "discard_stopped@example.com")
    session_id = client.post("/api/v1/sessions/", headers=headers).json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)

    from app.models.session import ConsultationSession
    db = SessionLocal()
    try:
        stored = db.query(ConsultationSession).filter(
            ConsultationSession.id == session_id
        ).first()
        stored.status = SessionStatus.STOPPED
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/v1/sessions/{session_id}/discard", headers=headers)

    assert response.status_code == 409
    assert "clinical content" in response.json()["detail"]


def test_discard_is_not_repeatable(client):
    headers = _discard_auth(client, "discard_twice@example.com")
    session_id = client.post("/api/v1/sessions/", headers=headers).json()["id"]

    assert client.post(f"/api/v1/sessions/{session_id}/discard", headers=headers).status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/discard", headers=headers).status_code == 409


def test_discard_denies_another_doctors_session(client):
    owner = _discard_auth(client, "discard_owner@example.com")
    intruder = _discard_auth(client, "discard_intruder@example.com")

    session_id = client.post("/api/v1/sessions/", headers=owner).json()["id"]

    response = client.post(f"/api/v1/sessions/{session_id}/discard", headers=intruder)
    assert response.status_code == 404


def test_discard_requires_authentication(client):
    assert client.post("/api/v1/sessions/1/discard").status_code == 401
