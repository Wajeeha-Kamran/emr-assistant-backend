import pytest
from fastapi.testclient import TestClient
from simulated_emr_service.main import app
from simulated_emr_service.models import SessionLocal
import time
from datetime import datetime, timezone

client = TestClient(app)

@pytest.fixture
def emr_db():
    db = SessionLocal()
    created_ids = []
    try:
        yield db, created_ids
    finally:
        if created_ids:
            from sqlalchemy import text
            db.execute(text(f"DELETE FROM simulated_emr_records WHERE id IN ({','.join(map(str, created_ids))})"))
            db.commit()
        db.close()

def get_valid_payload():
    return {
        "source_session_id": 123,
        "source_soap_note_id": 456,
        "session": {
            "started_at": "2026-08-14T10:00:00Z",
            "stopped_at": "2026-08-14T10:15:00Z",
            "duration_seconds": 900
        },
        "content": {
            "sections": {
                "SUBJECTIVE": "Patient complains of persistent headaches...",
                "OBJECTIVE": "Blood pressure elevated at 140/90...",
                "ASSESSMENT": "Primary hypertension...",
                "PLAN": "Prescribe Lisinopril 10mg daily..."
            },
            "code_suggestions": [
                {
                    "code": "I10",
                    "description": "Essential (primary) hypertension",
                    "code_type": "ICD10",
                    "rank": 1,
                    "accepted": True
                }
            ],
            "signature": {
                "doctor_id": 789,
                "doctor_name": "Dr. Smith",
                "signed_at": "2026-08-14T12:00:00Z",
                "method": "CONFIRMATION"
            }
        }
    }

def test_receive_record_success(emr_db):
    db, created_ids = emr_db
    payload = get_valid_payload()
    response = client.post("/simulated-emr/records", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["status"] == "received"
    created_ids.append(data["id"])

def test_receive_record_malformed():
    payload = get_valid_payload()
    # Remove a required field
    del payload["session"]
    response = client.post("/simulated-emr/records", json=payload)
    assert response.status_code == 422

def test_receive_record_different_timestamps(emr_db):
    db, created_ids = emr_db
    from simulated_emr_service.models import SimulatedEMRRecord
    
    payload1 = get_valid_payload()
    payload2 = get_valid_payload()
    payload2["source_session_id"] = 124
    
    r1 = client.post("/simulated-emr/records", json=payload1)
    # Ensure slightly different timestamp
    time.sleep(0.1)
    r2 = client.post("/simulated-emr/records", json=payload2)
    
    assert r1.status_code == 201
    assert r2.status_code == 201
    
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]
    created_ids.extend([id1, id2])
    
    record1 = db.query(SimulatedEMRRecord).filter(SimulatedEMRRecord.id == id1).first()
    record2 = db.query(SimulatedEMRRecord).filter(SimulatedEMRRecord.id == id2).first()
    
    # Assert timestamps are strictly different
    assert record1.received_at != record2.received_at
