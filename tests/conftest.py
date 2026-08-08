import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

from app.models.session import ConsultationSession
from app.models.audio import AudioMetadata
from app.models.transcript import Transcript, TranscriptSegment
from app.models.soap_note import SOAPNote, SOAPSection

@pytest.fixture(autouse=True)
def cleanup_test_data():
    def _clean():
        db = SessionLocal()
        try:
            test_emails = [
                "test@example.com",
                "dup@example.com",
                "login@example.com",
                "badpwd@example.com",
                "me@example.com",
                "doc_session@example.com",
                "doc_state@example.com",
                "doc_start_rec@example.com",
                "doc_other@example.com",
                "doc_audio@example.com",
                "doc_audio_dur@example.com",
                "doc_audio_type@example.com",
                "doc_audio_state@example.com",
                "doc_retention@example.com",
                "doc_soap@example.com",
                "doc_soap_api@example.com",
                "doc_other_api@example.com"
            ]
            doctors = db.query(Doctor).filter(Doctor.email.in_(test_emails)).all()
            doctor_ids = [doc.id for doc in doctors]
            
            if doctor_ids:
                session_ids = [s.id for s in db.query(ConsultationSession.id).filter(ConsultationSession.doctor_id.in_(doctor_ids)).all()]
                if session_ids:
                    # Clean up transcripts and segments first (FK dependencies)
                    transcript_ids = [t.id for t in db.query(Transcript.id).filter(Transcript.session_id.in_(session_ids)).all()]
                    if transcript_ids:
                        db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id.in_(transcript_ids)).delete(synchronize_session=False)
                        db.query(Transcript).filter(Transcript.id.in_(transcript_ids)).delete(synchronize_session=False)
                    
                    db.query(AudioMetadata).filter(AudioMetadata.session_id.in_(session_ids)).delete(synchronize_session=False)
                    
                    soap_note_ids = [n.id for n in db.query(SOAPNote.id).filter(SOAPNote.session_id.in_(session_ids)).all()]
                    if soap_note_ids:
                        db.query(SOAPSection).filter(SOAPSection.soap_note_id.in_(soap_note_ids)).delete(synchronize_session=False)
                        db.query(SOAPNote).filter(SOAPNote.id.in_(soap_note_ids)).delete(synchronize_session=False)
                    
                db.query(ConsultationSession).filter(ConsultationSession.doctor_id.in_(doctor_ids)).delete(synchronize_session=False)
                db.query(Doctor).filter(Doctor.id.in_(doctor_ids)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
            
    _clean()
    yield
    _clean()

import os
import shutil
from app.core.config import settings

@pytest.fixture(autouse=True)
def configure_test_storage():
    original_storage = settings.AUDIO_STORAGE_DIR
    test_storage = "./storage/test_audio"
    settings.AUDIO_STORAGE_DIR = test_storage
    
    if os.path.exists(test_storage):
        shutil.rmtree(test_storage)
    os.makedirs(test_storage, exist_ok=True)
    
    yield
    
    if os.path.exists(test_storage):
        shutil.rmtree(test_storage)
    settings.AUDIO_STORAGE_DIR = original_storage
