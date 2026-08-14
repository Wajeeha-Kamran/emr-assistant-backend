from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging

from app.api.v1.endpoints import auth, sessions, transcripts, soap_notes, code_suggestions, signatures, emr_sync, retention

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

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

app.add_exception_handler(Exception, global_exception_handler)

# CORS Middleware (Allow all for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/v1/admin/metrics")
def get_metrics():
    """Returns the pipeline metrics counters."""
    return metrics.get_metrics()

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(transcripts.router, prefix="/api/v1/sessions", tags=["transcripts"])
app.include_router(soap_notes.router, prefix="/api/v1/sessions", tags=["soap_notes"])
app.include_router(soap_notes.note_router, prefix="/api/v1/soap-notes", tags=["soap_notes"])
app.include_router(code_suggestions.router, prefix="/api/v1/soap-notes", tags=["code_suggestions"])
app.include_router(signatures.router, prefix="/api/v1/soap-notes", tags=["signatures"])
app.include_router(emr_sync.router, prefix="/api/v1/soap-notes", tags=["emr_sync"])
app.include_router(retention.router, prefix="/api/v1/admin", tags=["retention"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
