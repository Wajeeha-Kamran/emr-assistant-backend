from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import get_password_hash, verify_password, create_access_token
from app.db.session import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorResponse, Token
from app.api.deps import get_current_doctor

router = APIRouter()

@router.post("/register", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
def register(doctor_in: DoctorCreate, db: Session = Depends(get_db)):
    # Explicitly DO NOT log doctor_in or its password.
    existing_doctor = db.query(Doctor).filter(Doctor.email == doctor_in.email).first()
    if existing_doctor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    hashed_password = get_password_hash(doctor_in.password)
    new_doctor = Doctor(
        email=doctor_in.email,
        hashed_password=hashed_password,
        full_name=doctor_in.full_name
    )
    db.add(new_doctor)
    db.commit()
    db.refresh(new_doctor)
    return new_doctor

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Explicitly DO NOT log form_data.password.
    doctor = db.query(Doctor).filter(Doctor.email == form_data.username).first()
    if not doctor or not verify_password(form_data.password, doctor.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=doctor.email, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=DoctorResponse)
def read_users_me(current_doctor: Doctor = Depends(get_current_doctor)):
    return current_doctor
