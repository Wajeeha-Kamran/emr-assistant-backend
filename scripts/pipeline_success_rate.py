import time
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.core.security import create_access_token
import uuid

def main():
    print("Starting pipeline success rate measurement...")
    
    # 1. Setup test doctor
    db = SessionLocal()
    email = f"success_test_{uuid.uuid4()}@example.com"
    doc = Doctor(email=email, hashed_password="pw", full_name="Dr. Success")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    token = create_access_token(doc.email)
    headers = {"Authorization": f"Bearer {token}"}
    db.close()
    
    client = TestClient(app)
    
    from unittest.mock import patch, MagicMock
    import asyncio
    
    # Mock ClinicalBERT
    mock_engine = MagicMock()
    mock_engine.classify_doctor_segments.return_value = {"subjective": [], "objective": [], "assessment": [], "plan": []}
    patcher1 = patch("app.services.soap_service.ClinicalBERTEngine.get_instance", return_value=mock_engine)
    patcher1.start()
    
    # Mock ASR
    patcher2 = patch("app.services.asr_service.ASRService.transcribe_audio", return_value={"text": "Patient: Hello\nDoctor: Hi", "language": "en", "segments": []})
    patcher2.start()
    
    # Mock TinyTag to accept fake audio
    mock_tinytag = MagicMock()
    mock_tinytag.duration = 60.0
    patcher_tt = patch("app.services.audio_manager.TinyTag.get", return_value=mock_tinytag)
    patcher_tt.start()
    
    # Mock EMR Sync
    patcher3 = patch("httpx.Client.post")
    mock_post = patcher3.start()
    mock_post.return_value.status_code = 201
    mock_post.return_value.is_error = False
    
    ITERATIONS = 20 # 20 is enough to show 95% if 19/20 pass
    
    successes = 0
    failures = 0
    
    start_time = time.time()
    
    for i in range(ITERATIONS):
        try:
            # 1. Create Session
            resp = client.post("/api/v1/sessions/", headers=headers)
            if resp.status_code != 201:
                failures += 1
                continue
            session_id = resp.json()["id"]
            
            # 2. Start Recording
            resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)
            if resp.status_code not in [200, 202]:
                failures += 1
                continue
            
            # 3. Stop Recording & Upload Audio
            from io import BytesIO
            file_content = b"fake audio content"
            files = {"file": ("test.wav", BytesIO(file_content), "audio/wav")}
            resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers=headers, files=files)
            if resp.status_code not in [200, 202]:
                failures += 1
                continue
                
            # Wait a tiny bit for the background task (ASR) to mock complete
            time.sleep(0.5)
            
            # 4. Generate Draft
            resp = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)
            if resp.status_code != 201:
                failures += 1
                continue
                
            successes += 1
            print(f"Iteration {i+1}/{ITERATIONS}: SUCCESS")
        except Exception as e:
            print(f"Iteration {i+1}/{ITERATIONS}: FAILED with {e}")
            failures += 1
            
    total = successes + failures
    rate = (successes / total) * 100 if total > 0 else 0
    
    print("\n--- RESULTS ---")
    print(f"Total Runs: {total}")
    print(f"Successes: {successes}")
    print(f"Failures: {failures}")
    print(f"Success Rate: {rate:.2f}%")
    
    # Check internal metrics endpoint
    resp = client.get("/api/v1/admin/metrics")
    if resp.status_code == 200:
        print("\nInternal Metrics:")
        print(resp.json())
        
    if rate >= 95.0:
        print("\nSUCCESS: 95%+ requirement met.")
    else:
        print("\nFAILURE: 95%+ requirement NOT met.")

if __name__ == "__main__":
    main()
