from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.doctor import Doctor

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_doctor(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> Doctor:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Also case-insensitive, so a token issued before emails were normalised
    # still resolves. Otherwise a doctor holding a valid token would be logged
    # out with a 401 that looks like an expiry.
    doctor = db.query(Doctor).filter(func.lower(Doctor.email) == email.strip().lower()).first()
    if doctor is None:
        raise credentials_exception
    return doctor
