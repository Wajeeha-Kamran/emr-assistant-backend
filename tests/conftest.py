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
                "doc_state@example.com"
            ]
            doctors = db.query(Doctor).filter(Doctor.email.in_(test_emails)).all()
            doctor_ids = [doc.id for doc in doctors]
            
            if doctor_ids:
                db.query(ConsultationSession).filter(ConsultationSession.doctor_id.in_(doctor_ids)).delete(synchronize_session=False)
                db.query(Doctor).filter(Doctor.id.in_(doctor_ids)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
            
    _clean()
    yield
    _clean()
