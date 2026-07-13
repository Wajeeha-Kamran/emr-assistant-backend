from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_doctor
from app.db.session import get_db
from app.models.doctor import Doctor
from app.schemas.session import SessionResponse
from app.services.session_manager import SessionManager

router = APIRouter()

@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # No request body is accepted. The doctor_id is strictly sourced from the JWT.
    session = SessionManager.create_session(db=db, doctor_id=current_doctor.id)
    return session
