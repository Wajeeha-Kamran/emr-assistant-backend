from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
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
    """
    Register a new doctor account.

    The email must be unique; a duplicate returns 400. It must also look like an
    address, the name must not be blank, and the password must be at least 8
    characters — a malformed body returns 422. Surrounding whitespace on the
    email and name is trimmed, because an address stored with a trailing space
    could never be logged into: the login lookup is an exact match.

    Those rules apply to registration only. Sign-in does not re-check them, so
    accounts created before they existed continue to work.

    The password is hashed before storage and is never returned by any endpoint.

    Registration does not log you in — call /login next to obtain a token.
    """
    # Explicitly DO NOT log doctor_in or its password.
    # Compared case-insensitively. doctor_in.email is already lowercased by the
    # schema, so this only matters for rows written before that rule existed —
    # without it, an old "Doctor@clinic.com" row would not be seen as a
    # duplicate of a new "doctor@clinic.com" registration.
    existing_doctor = db.query(Doctor).filter(
        func.lower(Doctor.email) == doctor_in.email
    ).first()
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
    """
    Exchange email and password for a bearer token.

    Send as form data (`username` and `password`), not JSON — this follows the
    OAuth2 password flow so that interactive API docs can authorise directly.
    The `username` field takes the doctor's email address, matched without
    regard to capitalisation or surrounding whitespace.

    The password is matched exactly. Only the address is an identifier.

    Pass the returned token as `Authorization: Bearer <token>` on every other
    endpoint.
    """
    # Explicitly DO NOT log form_data.password.
    username = form_data.username.strip().lower()
    doctor = db.query(Doctor).filter(func.lower(Doctor.email) == username).first()
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
    # False positive: 'bearer' is the standard OAuth2 token_type string, not a hardcoded credential.
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105

@router.get("/me", response_model=DoctorResponse)
def read_users_me(current_doctor: Doctor = Depends(get_current_doctor)):
    """
    Return the currently authenticated doctor.

    Useful for confirming a token is valid and identifying whose session data
    the client is about to display.
    """
    return current_doctor
