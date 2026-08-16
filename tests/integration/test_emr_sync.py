import pytest
import uuid
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from httpx import Response, RequestError, HTTPStatusError, Request

from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType, SyncStatus
from app.models.code_suggestion import CodeSuggestion
from app.models.code_reference import CodeType
from app.models.signature import Signature
from app.services.emr_sync_client import EMRSyncClient
from app.core.security import create_access_token
from app.db.session import SessionLocal

# Import receiver's actual payload definition for contract testing
from simulated_emr_service.endpoints import SignedNotePayload

@pytest.fixture
def db():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

def setup_mock_note(db: Session, doc: Doctor):
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.STOPPED)
    db.add(session)
    db.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.SIGNED)
    db.add(note)
    db.commit()
    
    sig = Signature(soap_note_id=note.id, doctor_id=doc.id)
    db.add(sig)
    
    s1 = SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Sub")
    db.add(s1)
    
    cs1 = CodeSuggestion(soap_note_id=note.id, code="I10", description="HTN", code_type=CodeType.ICD10, rank=1, accepted=True, confidence_score=0.9)
    cs2 = CodeSuggestion(soap_note_id=note.id, code="99213", description="Visit", code_type=CodeType.CPT, rank=2, accepted=False, confidence_score=0.8)
    db.add_all([cs1, cs2])
    db.commit()
    return note

@pytest.fixture
def doc(db: Session):
    d = Doctor(email=f"test_sync_{uuid.uuid4()}@example.com", hashed_password="pw", full_name="Dr. Sync")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d

def test_contract_validation(db: Session, doc: Doctor):
    """
    Contract Test: Guarantees our builder perfectly matches the simulated EMR's Pydantic schema
    """
    note = setup_mock_note(db, doc)
    note.session.audio = None # Fallback to timestamps
    db.commit()
    
    # We patch httpx.Client.post to capture the exact payload before it's sent
    with patch("httpx.Client.post") as mock_post:
        # Mock a successful response
        mock_response = Response(201, json={"id": 1, "status": "received"})
        mock_response.request = Request("POST", "http://test")
        mock_post.return_value = mock_response
        
        EMRSyncClient.sync_note_to_emr(note.id)
        
        mock_post.assert_called_once()
        sent_payload = mock_post.call_args[1]["json"]
        
        # This will raise ValidationError if it doesn't match perfectly
        parsed = SignedNotePayload(**sent_payload)
        
        # Verify specific contract requirements
        assert parsed.content.signature.doctor_name == doc.full_name
        assert len(parsed.content.code_suggestions) == 1
        assert parsed.content.code_suggestions[0].code == "I10"

def test_fractional_duration_type_guard(db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    
    with patch("app.services.emr_sync_client.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        mock_note = MagicMock()
        mock_note.id = 999
        mock_note.session.audio.duration_seconds = 900.5
        mock_note.suggestions = []
        mock_note.sections = []
        mock_note.signature.doctor_id = doc.id
        mock_note.session.doctor.full_name = doc.full_name
        
        mock_db.query().filter().first.return_value = mock_note
        
        with patch("httpx.Client.post") as mock_post:
            mock_response = Response(201)
            mock_response.request = Request("POST", "http://test")
            mock_post.return_value = mock_response
            
            EMRSyncClient.sync_note_to_emr(999)
            
            sent_payload = mock_post.call_args[1]["json"]
            assert type(sent_payload["session"]["duration_seconds"]) is int
            assert sent_payload["session"]["duration_seconds"] == 900

def test_sync_success_tc09(db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    
    with patch("httpx.Client.post") as mock_post:
        mock_response = Response(201, json={"id": 1})
        mock_response.request = Request("POST", "http://test")
        mock_post.return_value = mock_response
        
        EMRSyncClient.sync_note_to_emr(note.id)
        
        db.refresh(note)
        assert note.sync_status == SyncStatus.SUCCESS
        assert note.status == SOAPNoteStatus.SIGNED

def test_sync_forced_failure_tc10(db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    
    with patch("httpx.Client.post") as mock_post:
        # Simulate network timeout
        mock_post.side_effect = RequestError("Timeout")
        
        # Patch sleep to not wait in tests
        with patch("time.sleep"):
            EMRSyncClient.sync_note_to_emr(note.id)
            
        assert mock_post.call_count == 3
        
        db.refresh(note)
        assert note.sync_status == SyncStatus.FAILED
        
        # TC-10 requirements: note must survive fully intact
        assert note.status == SOAPNoteStatus.SIGNED
        assert note.signature is not None
        assert note.signature.doctor_id == doc.id

def test_sync_4xx_fail_fast(db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    
    with patch("httpx.Client.post") as mock_post:
        # Simulate 422 Unprocessable Entity
        mock_response = Response(422, text="Validation Error")
        mock_response.request = Request("POST", "http://test")
        mock_post.return_value = mock_response
        
        with patch("time.sleep") as mock_sleep:
            EMRSyncClient.sync_note_to_emr(note.id)
            
        # Fail-fast: should only be called ONCE, no retries
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()
        
        db.refresh(note)
        assert note.sync_status == SyncStatus.FAILED
        
        # Note still intact
        assert note.status == SOAPNoteStatus.SIGNED
        assert note.signature is not None

def test_get_sync_status_api(client: TestClient, db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.PENDING
    db.commit()
    
    token = create_access_token(subject=doc.email)
    res = client.get(f"/api/v1/soap-notes/{note.id}/sync-status", headers={"Authorization": f"Bearer {token}"})
    
    assert res.status_code == 200
    assert res.json() == {"sync_status": "PENDING"}


# ---------------------------------------------------------------------------
# POST /{note_id}/retry-sync
#
# EMRSyncClient retries three times inside one job. Once those are exhausted
# the note is left FAILED and nothing re-sends it, so without this endpoint the
# consultation never reaches the EMR and its audio is never eligible for
# deletion (the retention worker requires sync_status == SUCCESS).
# ---------------------------------------------------------------------------

RETRY_TARGET = "app.api.v1.endpoints.emr_sync.EMRSyncClient.sync_note_to_emr"


def test_retry_sync_requeues_a_failed_note(client: TestClient, db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.FAILED
    db.commit()

    token = create_access_token(subject=doc.email)

    with patch(RETRY_TARGET) as mock_sync:
        res = client.post(
            f"/api/v1/soap-notes/{note.id}/retry-sync",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    assert res.json() == {"sync_status": "PENDING"}

    # TestClient runs background tasks before returning, so the job is queued
    # against the same note id signing would have used.
    mock_sync.assert_called_once_with(note.id)

    db.refresh(note)
    assert note.sync_status == SyncStatus.PENDING
    # The signature is untouched. Retrying a delivery is not re-signing.
    assert note.status == SOAPNoteStatus.SIGNED
    assert note.signature is not None


def test_retry_sync_rejects_a_successful_note(client: TestClient, db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.SUCCESS
    db.commit()

    token = create_access_token(subject=doc.email)

    with patch(RETRY_TARGET) as mock_sync:
        res = client.post(
            f"/api/v1/soap-notes/{note.id}/retry-sync",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 409
    mock_sync.assert_not_called()

    db.refresh(note)
    assert note.sync_status == SyncStatus.SUCCESS


def test_retry_sync_rejects_a_pending_note(client: TestClient, db: Session, doc: Doctor):
    """A job already in flight must not be duplicated; the EMR would store it twice."""
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.PENDING
    db.commit()

    token = create_access_token(subject=doc.email)

    with patch(RETRY_TARGET) as mock_sync:
        res = client.post(
            f"/api/v1/soap-notes/{note.id}/retry-sync",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 409
    mock_sync.assert_not_called()


def test_retry_sync_rejects_an_unsigned_note(client: TestClient, db: Session, doc: Doctor):
    """sync_status is null until signing, so there is no delivery to retry."""
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.STOPPED)
    db.add(session)
    db.commit()
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db.add(note)
    db.commit()
    db.refresh(note)

    token = create_access_token(subject=doc.email)

    with patch(RETRY_TARGET) as mock_sync:
        res = client.post(
            f"/api/v1/soap-notes/{note.id}/retry-sync",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 409
    mock_sync.assert_not_called()


def test_retry_sync_denies_another_doctors_note(client: TestClient, db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.FAILED
    db.commit()

    intruder = Doctor(
        email=f"test_sync_intruder_{uuid.uuid4()}@example.com",
        hashed_password="pw",
        full_name="Dr. Intruder",
    )
    db.add(intruder)
    db.commit()

    token = create_access_token(subject=intruder.email)

    with patch(RETRY_TARGET) as mock_sync:
        res = client.post(
            f"/api/v1/soap-notes/{note.id}/retry-sync",
            headers={"Authorization": f"Bearer {token}"},
        )

    # 404, not 403: the API does not confirm that another doctor's note exists.
    assert res.status_code == 404
    mock_sync.assert_not_called()

    db.refresh(note)
    assert note.sync_status == SyncStatus.FAILED


def test_retry_sync_requires_authentication(client: TestClient, db: Session, doc: Doctor):
    note = setup_mock_note(db, doc)
    note.sync_status = SyncStatus.FAILED
    db.commit()

    res = client.post(f"/api/v1/soap-notes/{note.id}/retry-sync")
    assert res.status_code == 401
