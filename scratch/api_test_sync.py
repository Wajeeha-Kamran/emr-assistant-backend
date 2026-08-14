import time
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.core.security import create_access_token

client = TestClient(app)
db = SessionLocal()

import uuid
email = f"test_e2e_{uuid.uuid4()}@example.com"
doc = Doctor(email=email, hashed_password="pw", full_name="Dr. E2E Test")
db.add(doc)
db.commit()
db.refresh(doc)

token = create_access_token(subject=doc.email)
headers = {"Authorization": f"Bearer {token}"}

session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
db.add(session)
db.commit()
db.refresh(session)

note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
db.add(note)
db.commit()
db.refresh(note)

db.add_all([
    SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Patient has a headache."),
    SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.OBJECTIVE, content="BP 140/90"),
    SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Hypertension"),
    SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Rest")
])
db.commit()

# Generate suggestions
response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
suggestions = response.json()
first_sug = suggestions[0]

# Accept the first suggestion
client.patch(f"/api/v1/soap-notes/{note.id}/code-suggestions/{first_sug['id']}", json={"accepted": True}, headers=headers)

# Sign the note (triggers sync background task)
print("Signing note...")
sign_res = client.post(f"/api/v1/soap-notes/{note.id}/sign", headers=headers)
print("Sign response:", sign_res.status_code, sign_res.json())

# Fetch sync status
status_res = client.get(f"/api/v1/soap-notes/{note.id}/sync-status", headers=headers)
print("Sync status:", status_res.status_code, status_res.json())

print("Note ID:", note.id)
