"""
Tests for GET /api/v1/attention — the dashboard's exception list.

The endpoint answers one question: which of this doctor's consultations did not
complete? Everything here is about what belongs on that list and, just as
importantly, what does not. A list that reports healthy consultations as stuck
is worse than no list, because the doctor learns to ignore it.

A consultation runs record -> transcribe -> generate note -> sign -> sync, and
every stage has a test for both its stuck and its healthy state.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.audio import AudioMetadata
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.signature import Signature
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SyncStatus, GenerationStatus
from app.models.transcript import Transcript, TranscriptStatus

PAST_GRACE = settings.ATTENTION_GRACE_MINUTES + 10


def ago(minutes: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


@pytest.fixture
def db():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture
def doc(db: Session):
    d = Doctor(
        email=f"test_attention_{uuid.uuid4()}@example.com",
        hashed_password="pw",
        full_name="Dr. Attention",
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@pytest.fixture
def auth(doc: Doctor):
    return {"Authorization": f"Bearer {create_access_token(subject=doc.email)}"}


def make_session(db: Session, doctor: Doctor, age_minutes: float = 0) -> ConsultationSession:
    session = ConsultationSession(
        doctor_id=doctor.id,
        status=SessionStatus.STOPPED,
        created_at=ago(age_minutes),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def add_audio(db: Session, session: ConsultationSession, duration: float = 60.0):
    db.add(AudioMetadata(
        session_id=session.id,
        file_path=f"./storage/test_audio/{session.id}.wav",
        duration_seconds=duration,
        format="wav",
    ))
    db.commit()


def add_transcript(
    db: Session,
    session: ConsultationSession,
    status: TranscriptStatus,
    age_minutes: float = 0,
) -> Transcript:
    transcript = Transcript(
        session_id=session.id,
        status=status,
        created_at=ago(age_minutes),
        finalized_at=ago(age_minutes) if status == TranscriptStatus.completed else None,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    return transcript


def add_note(
    db: Session,
    session: ConsultationSession,
    doctor: Doctor,
    status: SOAPNoteStatus,
    sync_status: SyncStatus | None = None,
    generation_status: GenerationStatus = GenerationStatus.completed,
    codes_generation_status: GenerationStatus | None = None,
    age_minutes: float = 0,
    generation_started_minutes_ago: float | None = None,
    codes_generation_started_minutes_ago: float | None = None,
) -> SOAPNote:
    # The started_at arguments default to None so the existing tests keep
    # exercising the created_at fallback, which is what rows written before
    # those columns existed will hit.
    note = SOAPNote(
        session_id=session.id,
        status=status,
        sync_status=sync_status,
        generation_status=generation_status,
        codes_generation_status=codes_generation_status,
        created_at=ago(age_minutes),
        generation_started_at=(
            ago(generation_started_minutes_ago)
            if generation_started_minutes_ago is not None else None
        ),
        codes_generation_started_at=(
            ago(codes_generation_started_minutes_ago)
            if codes_generation_started_minutes_ago is not None else None
        ),
    )
    db.add(note)
    db.commit()
    if status == SOAPNoteStatus.SIGNED:
        db.add(Signature(soap_note_id=note.id, doctor_id=doctor.id))
        db.commit()
    db.refresh(note)
    return note


def get_items(client: TestClient, auth) -> dict:
    res = client.get("/api/v1/attention", headers=auth)
    assert res.status_code == 200
    return res.json()


# ---------------------------------------------------------------------------
# Nothing stuck
# ---------------------------------------------------------------------------

def test_empty_when_a_consultation_completed(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=200)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=200)
    add_note(db, session, doc, SOAPNoteStatus.SIGNED, SyncStatus.SUCCESS, age_minutes=200)

    body = get_items(client, auth)
    assert body["count"] == 0
    assert body["items"] == []
    assert set(body["counts"].values()) == {0}


def test_requires_authentication(client: TestClient):
    assert client.get("/api/v1/attention").status_code == 401


def test_is_scoped_to_the_current_doctor(client: TestClient, db: Session, doc: Doctor, auth):
    other = Doctor(
        email=f"test_attention_other_{uuid.uuid4()}@example.com",
        hashed_password="pw",
        full_name="Dr. Other",
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    session = make_session(db, other, age_minutes=PAST_GRACE)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.failed, age_minutes=PAST_GRACE)

    assert get_items(client, auth)["count"] == 0


# ---------------------------------------------------------------------------
# Stage 1 — transcription
# ---------------------------------------------------------------------------

def test_reports_a_failed_transcript(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=30)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.failed, age_minutes=30)

    body = get_items(client, auth)
    assert body["count"] == 1
    item = body["items"][0]
    assert item["reason"] == "TRANSCRIPT_FAILED"
    assert item["action"] == "RESUME_TRANSCRIPTION"
    assert item["session_id"] == session.id
    assert item["note_id"] is None


def test_reports_a_stalled_transcript(client: TestClient, db: Session, doc: Doctor, auth):
    """Still `processing` long past the ASR budget: the process died mid-job."""
    session = make_session(db, doc, age_minutes=600)
    add_audio(db, session, duration=60.0)
    add_transcript(db, session, TranscriptStatus.processing, age_minutes=600)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "TRANSCRIPT_STALLED"
    assert body["items"][0]["action"] == "RESUME_TRANSCRIPTION"


def test_ignores_a_transcript_still_inside_its_budget(client: TestClient, db: Session, doc: Doctor, auth):
    """Transcription is slower than real time. A job still within its budget is working, not stuck."""
    session = make_session(db, doc, age_minutes=1)
    add_audio(db, session, duration=60.0)
    add_transcript(db, session, TranscriptStatus.processing, age_minutes=1)

    assert get_items(client, auth)["count"] == 0


def test_ignores_a_session_that_never_stopped_recording(client: TestClient, db: Session, doc: Doctor, auth):
    """No audio was stored and no transcript row exists, so nothing can be resumed."""
    session = ConsultationSession(
        doctor_id=doc.id,
        status=SessionStatus.RECORDING,
        created_at=ago(PAST_GRACE),
    )
    db.add(session)
    db.commit()

    assert get_items(client, auth)["count"] == 0


# ---------------------------------------------------------------------------
# Stage 2 — note generation
# ---------------------------------------------------------------------------

def test_reports_a_transcript_with_no_note(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=PAST_GRACE)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=PAST_GRACE)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "NOTE_NOT_GENERATED"
    assert body["items"][0]["action"] == "GENERATE_NOTE"


def test_ignores_a_fresh_transcript_with_no_note(client: TestClient, db: Session, doc: Doctor, auth):
    """The doctor is reading the transcript right now."""
    session = make_session(db, doc, age_minutes=1)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=1)

    assert get_items(client, auth)["count"] == 0


# ---------------------------------------------------------------------------
# Stage 3 — signing
# ---------------------------------------------------------------------------

def test_reports_an_unsigned_note(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=PAST_GRACE)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=PAST_GRACE)
    note = add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.completed, age_minutes=PAST_GRACE)

    body = get_items(client, auth)
    assert body["count"] == 1
    item = body["items"][0]
    assert item["reason"] == "NOT_SIGNED"
    assert item["action"] == "SIGN_NOTE"
    assert item["note_id"] == note.id
    assert item["session_id"] == session.id


def test_ignores_a_note_being_written_now(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=2)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=2)
    add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.completed, age_minutes=2)

    assert get_items(client, auth)["count"] == 0

def test_reports_soap_generation_failed(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    note = add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.failed, age_minutes=5)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "SOAP_GENERATION_FAILED"
    assert body["items"][0]["action"] == "RETRY_SOAP_GENERATION"

def test_reports_soap_generation_stalled(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    note = add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.processing, age_minutes=5)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "SOAP_GENERATION_STALLED"
    assert body["items"][0]["action"] == "RETRY_SOAP_GENERATION"

def test_reports_codes_generation_failed(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    note = add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.completed, codes_generation_status=GenerationStatus.failed, age_minutes=5)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "CODES_GENERATION_FAILED"
    assert body["items"][0]["action"] == "RETRY_CODES_GENERATION"

def test_reports_codes_generation_stalled(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    note = add_note(db, session, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.completed, codes_generation_status=GenerationStatus.processing, age_minutes=5)

    body = get_items(client, auth)
    assert body["count"] == 1
    assert body["items"][0]["reason"] == "CODES_GENERATION_STALLED"
    assert body["items"][0]["action"] == "RETRY_CODES_GENERATION"


# The two tests above prove a stalled job is reported. These prove a job that is
# genuinely running is not — which is the half that was missing, and the half
# that fails if the deadline is measured from note.created_at instead of from
# when the job started. Both notes here are old; only the jobs are new.

def test_ignores_soap_generation_that_just_started(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=PAST_GRACE)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=PAST_GRACE)
    # A retry on an old note: created long ago, generation restarted just now.
    add_note(
        db, session, doc, SOAPNoteStatus.DRAFT,
        generation_status=GenerationStatus.processing,
        age_minutes=PAST_GRACE,
        generation_started_minutes_ago=0,
    )

    assert get_items(client, auth)["count"] == 0


def test_ignores_codes_generation_that_just_started(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=PAST_GRACE)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=PAST_GRACE)
    # The ordinary case: the doctor read the draft before asking for codes, so
    # the note is far older than the job.
    add_note(
        db, session, doc, SOAPNoteStatus.DRAFT,
        generation_status=GenerationStatus.completed,
        codes_generation_status=GenerationStatus.processing,
        age_minutes=PAST_GRACE,
        codes_generation_started_minutes_ago=0,
    )

    # This note is old, unsigned and finished generating, so NOT_SIGNED is the
    # correct row for it. What must not appear is a stall: the codes job started
    # a moment ago. Asserting on the reason rather than the count keeps this
    # test about stall detection and nothing else.
    reasons = [item["reason"] for item in get_items(client, auth)["items"]]
    assert "CODES_GENERATION_STALLED" not in reasons


# ---------------------------------------------------------------------------
# Stage 4 — sync
# ---------------------------------------------------------------------------

def test_reports_a_failed_sync(client: TestClient, db: Session, doc: Doctor, auth):
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    note = add_note(db, session, doc, SOAPNoteStatus.SIGNED, SyncStatus.FAILED, age_minutes=5)

    body = get_items(client, auth)
    assert body["count"] == 1
    item = body["items"][0]
    assert item["reason"] == "SYNC_FAILED"
    assert item["action"] == "RETRY_SYNC"
    assert item["note_id"] == note.id


def test_ignores_a_sync_in_flight(client: TestClient, db: Session, doc: Doctor, auth):
    """A push still running is not stuck. Reporting it would alarm the doctor mid-send."""
    session = make_session(db, doc, age_minutes=5)
    add_audio(db, session)
    add_transcript(db, session, TranscriptStatus.completed, age_minutes=5)
    add_note(db, session, doc, SOAPNoteStatus.SIGNED, SyncStatus.PENDING, age_minutes=5)

    assert get_items(client, auth)["count"] == 0


# ---------------------------------------------------------------------------
# All stages together
# ---------------------------------------------------------------------------

def test_reports_every_stage_at_once_newest_first(client: TestClient, db: Session, doc: Doctor, auth):
    failed_transcript = make_session(db, doc, age_minutes=50)
    add_audio(db, failed_transcript)
    add_transcript(db, failed_transcript, TranscriptStatus.failed, age_minutes=50)

    no_note = make_session(db, doc, age_minutes=60)
    add_audio(db, no_note)
    add_transcript(db, no_note, TranscriptStatus.completed, age_minutes=60)

    unsigned = make_session(db, doc, age_minutes=70)
    add_audio(db, unsigned)
    add_transcript(db, unsigned, TranscriptStatus.completed, age_minutes=70)
    add_note(db, unsigned, doc, SOAPNoteStatus.DRAFT, generation_status=GenerationStatus.completed, age_minutes=70)

    failed_sync = make_session(db, doc, age_minutes=80)
    add_audio(db, failed_sync)
    add_transcript(db, failed_sync, TranscriptStatus.completed, age_minutes=80)
    add_note(db, failed_sync, doc, SOAPNoteStatus.SIGNED, SyncStatus.FAILED, age_minutes=80)

    healthy = make_session(db, doc, age_minutes=90)
    add_audio(db, healthy)
    add_transcript(db, healthy, TranscriptStatus.completed, age_minutes=90)
    add_note(db, healthy, doc, SOAPNoteStatus.SIGNED, SyncStatus.SUCCESS, age_minutes=90)

    body = get_items(client, auth)

    assert body["count"] == 4
    assert body["counts"]["TRANSCRIPT_FAILED"] == 1
    assert body["counts"]["NOTE_NOT_GENERATED"] == 1
    assert body["counts"]["NOT_SIGNED"] == 1
    assert body["counts"]["SYNC_FAILED"] == 1
    assert body["counts"]["TRANSCRIPT_STALLED"] == 0

    # Newest consultation first.
    assert [item["session_id"] for item in body["items"]] == [
        failed_transcript.id,
        no_note.id,
        unsigned.id,
        failed_sync.id,
    ]
