from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_doctor
from app.models.doctor import Doctor
from app.schemas.attention import AttentionReason, AttentionResponse
from app.services.attention_service import AttentionService

router = APIRouter()


@router.get(
    "/attention",
    response_model=AttentionResponse,
    summary="Consultations that did not complete",
)
def list_attention_items(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    List the current doctor's consultations that are stuck, so the client can
    offer a way back into each one.

    This is an exception list, not a work queue. Under normal use it is empty.

    A consultation runs record -> transcribe -> generate note -> sign -> sync.
    Any stage can be interrupted, and none recovers on its own, so each has a
    reason here and a recovery action:

    | reason | what happened | action |
    |---|---|---|
    | TRANSCRIPT_FAILED | Transcription errored or exceeded its time budget | RESUME_TRANSCRIPTION |
    | TRANSCRIPT_STALLED | Still `processing` past the point where the job could be running — the process died mid-job | RESUME_TRANSCRIPTION |
    | NOTE_NOT_GENERATED | Transcript ready, note never generated | GENERATE_NOTE |
    | NOT_SIGNED | Note drafted, never signed | SIGN_NOTE |
    | SYNC_FAILED | Signed, but the push to the EMR failed and nothing re-sends it | RETRY_SYNC |

    Signing never appears: it is synchronous, so a failure is returned to the
    caller and nothing is written.

    Beyond letting the doctor finish the consultation, this list is how the
    system stops accumulating recordings. Audio is deleted only when its note
    is both SIGNED and SUCCESS, so every consultation stuck at any stage above
    keeps a recording of a patient's voice on disk indefinitely.

    Two exclusions are deliberate. A note or transcript younger than
    ATTENTION_GRACE_MINUTES is not reported, so work in progress never appears
    in its own author's attention list. A session whose recording was started
    but never stopped is not reported either — no audio was stored and no
    transcript exists, so there is nothing to resume and nothing to clean up.

    Every item carries session_id, which is what the client navigates with: the
    transcript and the note are both fetched by session.
    """
    items = AttentionService.collect(db, current_doctor)

    counts = {reason: 0 for reason in AttentionReason}
    for item in items:
        counts[item.reason] += 1

    return AttentionResponse(items=items, count=len(items), counts=counts)
