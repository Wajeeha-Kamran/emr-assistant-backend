from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging

from app.api.v1.endpoints import auth, sessions, transcripts, soap_notes, code_suggestions, signatures, emr_sync, retention, attention

setup_logging()

from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from app.workers.retention_worker import RetentionWorker
from app.core.error_handlers import global_exception_handler
from app.core.metrics import metrics

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    scheduler.add_job(
        RetentionWorker.run_cleanup,
        "interval",
        seconds=settings.RETENTION_SWEEP_INTERVAL_SECONDS,
        id="retention_sweep",
        replace_existing=True,
    )
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown(wait=False)

API_DESCRIPTION = """
Backend for an AI-assisted clinical documentation system. A doctor records a
consultation; the system transcribes it, separates the two speakers, drafts a
SOAP note, suggests billing codes, and syncs the signed note to an EMR.

## The workflow

Endpoints are designed to be called in this order. Each step depends on the one
before it, and the session's state machine enforces that.

1. `POST /auth/register` then `POST /auth/login` — obtain a bearer token
2. `POST /sessions/` — create a consultation session
3. `POST /sessions/{id}/start-recording` — session becomes RECORDING
4. `POST /sessions/{id}/stop-recording` — upload the audio; transcription starts
   in the background
5. `GET /sessions/{id}/transcript` — poll until `status` is `completed`
6. `POST /sessions/{id}/soap-notes/generate` — draft the note
7. `PATCH /soap-notes/{id}/sections/{section_id}` — the doctor edits the draft
8. `POST /soap-notes/{id}/code-suggestions/generate` — ranked ICD-10 and CPT codes
9. `POST /soap-notes/{id}/sign` — the note becomes immutable and syncs to the EMR
10. `GET /soap-notes/{id}/sync-status` — confirm the sync

## Things worth knowing before integrating

**The note is a draft, not a record.** Everything generated here is intended for
a clinician to review and correct before signing. Signing is the point at which it
becomes a clinical record, and after that the note is immutable — edits and
regenerated code suggestions are both rejected.

**Transcription is asynchronous.** `stop-recording` returns as soon as the audio
is stored. Transcription runs in the background and takes roughly as long as the
recording itself on CPU. Poll the transcript endpoint; do not assume it is ready.

**Ownership is enforced everywhere.** A doctor can only reach their own sessions
and notes. Requests for another doctor's resources return 404, not 403, so the
API does not confirm that a resource exists.

**Audio is deleted after a retention window.** Recordings are removed once the
note has synced and the window has elapsed. Do not treat stored audio as durable.

## Known limitations, measured rather than assumed

- Speaker separation meets its accuracy target when the two voices are
  acoustically distinguishable and speak at a conversational pace. It degrades
  when voices are similar or turn-taking is rapid. See `docs/module_9_1_accuracy.md`.
- SOAP Assessment classification is weak: diagnostic statements are frequently
  filed under Objective. See `docs/module_3_soap_classification.md`.
- Transcription is CPU-bound and does not meet the SRS timing target without a
  GPU. See `docs/module_8_3_performance.md`.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Registration, login, and the current doctor. Every other endpoint requires the bearer token issued here."},
    {"name": "sessions", "description": "Consultation lifecycle and audio upload. The session's state machine governs what may happen next."},
    {"name": "transcripts", "description": "Speech recognition and speaker separation results. Transcription runs in the background; poll for completion."},
    {"name": "soap_notes", "description": "Drafting and editing the SOAP note. Draft notes are editable; signed notes are not."},
    {"name": "code_suggestions", "description": "Ranked ICD-10 and CPT suggestions derived from the note's Assessment and Plan sections."},
    {"name": "signatures", "description": "Signing a note. This is the point at which a draft becomes an immutable clinical record."},
    {"name": "emr_sync", "description": "Status of the background push to the external EMR, triggered by signing."},
    {"name": "attention", "description": "Consultations that did not complete — unsigned notes and failed EMR syncs. Empty under normal use."},
    {"name": "retention", "description": "Audio retention enforcement. Development and administrative use."},
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=API_DESCRIPTION,
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

app.add_exception_handler(Exception, global_exception_handler)

# CORS. allow_origins=["*"] is a DEVELOPMENT setting: it permits any website to
# call this API with the user's credentials. Restrict it to the frontend's real
# origin before deployment (tracked in Module 10.3). Left open for now so the
# .NET MAUI client and any browser tooling can connect without configuration.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["health"], summary="Liveness check")
def health_check():
    """
    Returns 200 while the application is running.

    Checks nothing beyond the process itself — not the database, not the ML
    models. A 200 here means the API is up, not that a consultation can be
    processed. Suitable for a container liveness probe.
    """
    return {"status": "ok"}

@app.get("/api/v1/admin/metrics", tags=["retention"], summary="Pipeline success counters")
def get_metrics():
    """
    Success and failure counts for the ASR and SOAP generation stages since the
    process started.

    In-memory and not persisted, so the counters reset on restart. Intended for
    development observation rather than production monitoring.
    """
    return metrics.get_metrics()

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(transcripts.router, prefix="/api/v1/sessions", tags=["transcripts"])
app.include_router(soap_notes.router, prefix="/api/v1/sessions", tags=["soap_notes"])
app.include_router(soap_notes.note_router, prefix="/api/v1/soap-notes", tags=["soap_notes"])
app.include_router(code_suggestions.router, prefix="/api/v1/soap-notes", tags=["code_suggestions"])
app.include_router(signatures.router, prefix="/api/v1/soap-notes", tags=["signatures"])
app.include_router(emr_sync.router, prefix="/api/v1/soap-notes", tags=["emr_sync"])
app.include_router(attention.router, prefix="/api/v1", tags=["attention"])
app.include_router(retention.router, prefix="/api/v1/admin", tags=["retention"])
