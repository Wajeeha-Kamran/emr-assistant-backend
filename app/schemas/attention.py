import enum
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class AttentionReason(str, enum.Enum):
    """Why a consultation did not finish.

    These are the only persistent stuck states the system has. Each one leaves
    the consultation's audio on disk permanently, because the retention worker
    deletes audio only when the note is both SIGNED and SUCCESS.

    Signing itself never appears here: it is synchronous, so a failure is
    reported to the caller and nothing is written.
    """

    TRANSCRIPT_FAILED = "TRANSCRIPT_FAILED"
    TRANSCRIPT_STALLED = "TRANSCRIPT_STALLED"
    SOAP_GENERATION_FAILED = "SOAP_GENERATION_FAILED"
    SOAP_GENERATION_STALLED = "SOAP_GENERATION_STALLED"
    CODES_GENERATION_FAILED = "CODES_GENERATION_FAILED"
    CODES_GENERATION_STALLED = "CODES_GENERATION_STALLED"
    NOTE_NOT_GENERATED = "NOTE_NOT_GENERATED"
    NOT_SIGNED = "NOT_SIGNED"
    SYNC_FAILED = "SYNC_FAILED"


class AttentionAction(str, enum.Enum):
    """What the client should offer for a stuck consultation.

    Included so the recovery path is decided in one place rather than
    re-derived from `reason` in every client.
    """

    RESUME_TRANSCRIPTION = "RESUME_TRANSCRIPTION"
    RETRY_SOAP_GENERATION = "RETRY_SOAP_GENERATION"
    RETRY_CODES_GENERATION = "RETRY_CODES_GENERATION"
    GENERATE_NOTE = "GENERATE_NOTE"
    SIGN_NOTE = "SIGN_NOTE"
    RETRY_SYNC = "RETRY_SYNC"


class AttentionItem(BaseModel):
    session_id: int
    # Absent for the stages that happen before a note exists.
    note_id: Optional[int] = None
    reason: AttentionReason
    action: AttentionAction
    # The consultation's own creation time, so the list reads in the order the
    # consultations happened rather than the order their failures were recorded.
    created_at: datetime
    last_edited_at: Optional[datetime] = None


class AttentionResponse(BaseModel):
    items: List[AttentionItem]
    count: int
    # Every reason is present, zero-filled, so a client never has to handle a
    # missing key.
    counts: Dict[AttentionReason, int]
