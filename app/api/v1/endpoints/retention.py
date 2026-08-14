"""
Development/demo endpoint for triggering the retention sweep manually.
NOT intended for production use — the APScheduler runs this automatically.
"""
from fastapi import APIRouter, Depends
from app.api.deps import get_current_doctor
from app.models.doctor import Doctor
from app.workers.retention_worker import RetentionWorker

router = APIRouter()

@router.post("/retention/sweep")
def trigger_retention_sweep(
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """
    Development aid: manually triggers one retention cleanup sweep.
    Requires authentication to prevent unauthenticated access.
    In production, this runs automatically via APScheduler.
    """
    deleted_count = RetentionWorker.run_cleanup()
    return {"deleted_count": deleted_count}
