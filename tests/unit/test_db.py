from sqlalchemy import text
from app.db.session import SessionLocal

def test_db_connection():
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        db.close()
