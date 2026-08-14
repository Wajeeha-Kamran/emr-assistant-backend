from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.core.security import create_access_token

client = TestClient(app)
db = SessionLocal()

# 1. Setup a real doctor and note
doc = Doctor(email="test_demo@example.com", hashed_password="pw", full_name="Dr. Demo")
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

# 2. Generate code suggestions via API
print("Generating suggestions...")
response = client.post(f"/api/v1/soap-notes/{note.id}/code-suggestions/generate", headers=headers)
suggestions = response.json()
print(f"Generated {len(suggestions)} suggestions.")

# 3. Accept the first one via API
first_sug = suggestions[0]
print(f"Accepting suggestion ID {first_sug['id']} ({first_sug['code']})...")
patch_res = client.patch(
    f"/api/v1/soap-notes/{note.id}/code-suggestions/{first_sug['id']}", 
    json={"accepted": True}, 
    headers=headers
)
print("PATCH Response:", patch_res.status_code, patch_res.json())

# Cleanup (optional, but let's keep the data so we can see it in psql!)
