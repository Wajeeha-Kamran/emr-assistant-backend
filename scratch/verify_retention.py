import os
import time
import httpx
from datetime import datetime, timezone, timedelta
from app.db.session import SessionLocal
from app.models.session import ConsultationSession
from app.models.transcript import Transcript, TranscriptSegment
from app.models.audio import AudioMetadata
from app.models.soap_note import SOAPNote, SOAPSection, SyncStatus
from app.models.signature import Signature
from app.models.code_suggestion import CodeSuggestion

API_URL = "http://localhost:8000/api/v1"

# Create a test doctor to ensure login works
db = SessionLocal()
from app.models.doctor import Doctor
doc_email = "sweep_test_doc@example.com"
doc = db.query(Doctor).filter(Doctor.email == doc_email).first()
if not doc:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    doc = Doctor(email=doc_email, full_name="Dr. Sweep", hashed_password=pwd_context.hash("password123"))
    db.add(doc)
    db.commit()
db.close()

response = httpx.post(f"{API_URL}/auth/login", data={"username": doc_email, "password": "password123"})
assert response.status_code == 200, f"Login failed: {response.text}"
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Create Session & Upload Audio
response = httpx.post(f"{API_URL}/sessions/", headers=headers)
assert response.status_code == 201, f"Failed to create session: {response.text}"
session_id = response.json()["id"]

# Start recording
httpx.post(f"{API_URL}/sessions/{session_id}/start-recording", headers=headers)

# Create a temporary file and upload it
import wave
temp_audio_path = f"test_audio_{session_id}.wav"
with wave.open(temp_audio_path, 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(44100)
    wf.writeframes(b'\x00\x00' * 44100) # 1 second of silence

with open(temp_audio_path, "rb") as f:
    files = {"file": (temp_audio_path, f, "audio/wav")}
    response = httpx.post(f"{API_URL}/sessions/{session_id}/stop-recording", headers=headers, files=files)
assert response.status_code == 200, f"Failed to stop recording: {response.text}"

# 3. Generate Draft Note
response = httpx.post(f"{API_URL}/sessions/{session_id}/soap-notes/generate", headers=headers, timeout=60.0)
assert response.status_code == 201, f"Failed to generate note: {response.text}"
note_id = response.json()["id"]

# 4. Sign the note (triggers sync and marks audio)
response = httpx.post(f"{API_URL}/soap-notes/{note_id}/sign", headers=headers)
assert response.status_code == 201, f"Failed to sign note: {response.text}"

# Wait for background sync to complete
db = SessionLocal()
for _ in range(15):
    time.sleep(2)
    note = db.query(SOAPNote).filter(SOAPNote.id == note_id).first()
    db.refresh(note)
    if note.sync_status == SyncStatus.SUCCESS:
        break

if note.sync_status != SyncStatus.SUCCESS:
    print(f"Sync failed or pending: {note.sync_status}")
    db.close()
    exit(1)

# Check that audio was marked
audio = db.query(AudioMetadata).filter(AudioMetadata.session_id == session_id).first()
if not audio or not audio.retention_marked_for_deletion_at:
    print("Audio was not marked for deletion!")
    db.close()
    exit(1)

# 5. Simulate 5 minutes passing by rewinding the marked time in the DB
audio.retention_marked_for_deletion_at = datetime.now(timezone.utc) - timedelta(minutes=5)
db.commit()

# Ensure file actually exists before we try to sweep
audio_path = audio.file_path
if not os.path.exists(audio_path):
    print(f"Wait, file {audio_path} doesn't exist to begin with.")
    db.close()
    exit(1)

# 6. Trigger Sweep
response = httpx.post(f"{API_URL}/admin/retention/sweep", headers=headers)
assert response.status_code == 200
deleted_count = response.json()["deleted_count"]

print(f"Sweep triggered, reported {deleted_count} deletions.")

# 7. Verify
db.refresh(audio)

if audio.deleted_at is not None and audio.file_path is None and not os.path.exists(audio_path):
    print("\nSUCCESS: Verification complete!")
    print(f"- audio.deleted_at: {audio.deleted_at}")
    print(f"- audio.file_path: {audio.file_path}")
    print(f"- Physical file exists: {os.path.exists(audio_path)}")
else:
    print("\nFAILURE: Artifacts were not deleted correctly.")
    
db.close()
if os.path.exists(temp_audio_path):
    os.remove(temp_audio_path)
