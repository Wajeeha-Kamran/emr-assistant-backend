import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.doctor import Doctor

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(autouse=True)
def cleanup_test_doctors():
    def _clean():
        db = SessionLocal()
        try:
            test_emails = [
                "test@example.com",
                "dup@example.com",
                "login@example.com",
                "badpwd@example.com",
                "me@example.com"
            ]
            db.query(Doctor).filter(Doctor.email.in_(test_emails)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
            
    _clean()
    yield
    _clean()
