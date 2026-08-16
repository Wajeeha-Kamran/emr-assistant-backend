import pytest
import os
from io import BytesIO
from app.models.session import SessionStatus
from tinytag import TinyTag

def mock_tinytag_get(duration):
    class MockTag:
        def __init__(self, d):
            self.duration = d
    return lambda filepath: MockTag(duration)

def test_stop_recording_happy_path(client, monkeypatch):
    monkeypatch.setattr(TinyTag, 'get', mock_tinytag_get(120.5)) # 2 minutes
    
    client.post("/api/v1/auth/register", json={"email": "doc_audio@example.com", "full_name": "Audio Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_audio@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    
    file_content = b"fake audio content"
    files = {"file": ("test.wav", BytesIO(file_content), "audio/wav")}
    
    stop_resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers={"Authorization": f"Bearer {token}"}, files=files)
    
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "STOPPED"
    assert stop_resp.json()["stopped_at"] is not None

def test_stop_recording_duration_limit(client, monkeypatch):
    monkeypatch.setattr(TinyTag, 'get', mock_tinytag_get(1900.0)) # > 30 mins
    
    client.post("/api/v1/auth/register", json={"email": "doc_audio_dur@example.com", "full_name": "Audio Dur Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_audio_dur@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    
    file_content = b"huge fake audio content"
    files = {"file": ("test.mp3", BytesIO(file_content), "audio/mp3")}
    
    stop_resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers={"Authorization": f"Bearer {token}"}, files=files)
    
    assert stop_resp.status_code == 400
    assert "exceeds maximum allowed duration" in stop_resp.json()["detail"]

def test_stop_recording_invalid_type(client):
    client.post("/api/v1/auth/register", json={"email": "doc_audio_type@example.com", "full_name": "Audio Type Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_audio_type@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    
    file_content = b"fake pdf content"
    files = {"file": ("test.pdf", BytesIO(file_content), "application/pdf")}
    
    stop_resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers={"Authorization": f"Bearer {token}"}, files=files)
    
    assert stop_resp.status_code == 400
    assert "Unsupported file type" in stop_resp.json()["detail"]

def test_stop_recording_invalid_state(client, monkeypatch):
    monkeypatch.setattr(TinyTag, 'get', mock_tinytag_get(120.0))
    client.post("/api/v1/auth/register", json={"email": "doc_audio_state@example.com", "full_name": "Audio State Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_audio_state@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    
    file_content = b"fake audio content"
    files = {"file": ("test.wav", BytesIO(file_content), "audio/wav")}
    
    stop_resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers={"Authorization": f"Bearer {token}"}, files=files)
    
    assert stop_resp.status_code == 409
    assert "Illegal state transition" in stop_resp.json()["detail"]

def test_stop_recording_too_long(client, monkeypatch):
    monkeypatch.setattr(TinyTag, 'get', mock_tinytag_get(1801.0))
    client.post("/api/v1/auth/register", json={"email": "doc_audio_long@example.com", "full_name": "Audio Long Doc", "password": "testpassword"})
    login_resp = client.post("/api/v1/auth/login", data={"username": "doc_audio_long@example.com", "password": "testpassword"})
    token = login_resp.json()["access_token"]
    
    create_resp = client.post("/api/v1/sessions/", headers={"Authorization": f"Bearer {token}"})
    session_id = create_resp.json()["id"]
    
    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers={"Authorization": f"Bearer {token}"})
    
    file_content = b"fake audio content"
    files = {"file": ("test.wav", BytesIO(file_content), "audio/wav")}
    
    stop_resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording", headers={"Authorization": f"Bearer {token}"}, files=files)
    
    assert stop_resp.status_code == 400
    assert "Audio exceeds maximum allowed duration" in stop_resp.json()["detail"]
