from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging

from app.api.v1.endpoints import auth, sessions, transcripts, soap_notes, code_suggestions, signatures, emr_sync

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(transcripts.router, prefix="/api/v1/sessions", tags=["transcripts"])
app.include_router(soap_notes.router, prefix="/api/v1/sessions", tags=["soap_notes"])
app.include_router(soap_notes.note_router, prefix="/api/v1/soap-notes", tags=["soap_notes"])
app.include_router(code_suggestions.router, prefix="/api/v1/soap-notes", tags=["code_suggestions"])
app.include_router(signatures.router, prefix="/api/v1/soap-notes", tags=["signatures"])
app.include_router(emr_sync.router, prefix="/api/v1/soap-notes", tags=["emr_sync"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
