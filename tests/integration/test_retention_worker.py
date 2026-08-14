import os
import uuid
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from httpx import Response, Request

from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.audio import AudioMetadata
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType, SyncStatus
from app.models.signature import Signature
from app.models.transcript import Transcript, TranscriptSegment
from app.workers.retention_worker import RetentionWorker
from app.services.emr_sync_client import EMRSyncClient
from app.services.session_manager import SessionManager


@pytest.fixture
def db():
    db_session = SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture
def doc(db: Session):
    d = Doctor(email=f"retention_test_{uuid.uuid4()}@example.com", hashed_password="pw", full_name="Dr. Retention")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _create_full_session(db: Session, doc: Doctor, sync_status: SyncStatus, marked_minutes_ago: int, tmp_path: str):
    """
    Helper: creates a session with audio file, signed note, signature, and transcript —
    the full artifact set needed for retention eligibility testing.
    """
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    session.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.stopped_at = datetime.now(timezone.utc) - timedelta(minutes=50)
    session.finalized_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.add(session)
    db.commit()
    db.refresh(session)

    # Create a real temp audio file
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(b"fake audio data")

    audio = AudioMetadata(
        session_id=session.id,
        file_path=tmp_path,
        duration_seconds=120.5,
        format="audio/wav",
        retention_marked_for_deletion_at=datetime.now(timezone.utc) - timedelta(minutes=marked_minutes_ago),
    )
    db.add(audio)
    db.commit()

    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.SIGNED, sync_status=sync_status)
    db.add(note)
    db.commit()
    db.refresh(note)

    sig = Signature(soap_note_id=note.id, doctor_id=doc.id)
    db.add(sig)

    section = SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Test content")
    db.add(section)

    transcript = Transcript(session_id=session.id)
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    segment = TranscriptSegment(transcript_id=transcript.id, speaker_role="DOCTOR", text="Test speech")
    db.add(segment)
    db.commit()

    return session, audio, note, transcript


def test_past_window_deletion(db: Session, doc: Doctor):
    """Audio file gone, deleted_at set, file_path cleared. Note/Signature/Transcript unchanged."""
    tmp_path = f"./storage/audio/test_retention_{uuid.uuid4()}.wav"

    session, audio, note, transcript = _create_full_session(
        db, doc, SyncStatus.SUCCESS, marked_minutes_ago=10, tmp_path=tmp_path
    )

    assert os.path.exists(tmp_path)

    deleted_count = RetentionWorker.run_cleanup()

    assert deleted_count == 1
    assert not os.path.exists(tmp_path)

    db.refresh(audio)
    assert audio.deleted_at is not None
    assert audio.file_path is None

    # Note, Signature, Transcript all still present and unchanged
    db.refresh(note)
    assert note.status == SOAPNoteStatus.SIGNED
    assert note.signature is not None
    assert note.signature.doctor_id == doc.id
    db.refresh(transcript)
    assert transcript is not None
    assert len(transcript.segments) > 0


def test_failed_sync_nothing_deleted(db: Session, doc: Doctor):
    """FAILED sync — nothing should be deleted."""
    tmp_path = f"./storage/audio/test_retention_{uuid.uuid4()}.wav"

    session, audio, note, transcript = _create_full_session(
        db, doc, SyncStatus.FAILED, marked_minutes_ago=10, tmp_path=tmp_path
    )

    deleted_count = RetentionWorker.run_cleanup()

    assert deleted_count == 0
    assert os.path.exists(tmp_path)

    db.refresh(audio)
    assert audio.deleted_at is None
    assert audio.file_path == tmp_path

    # Cleanup
    os.remove(tmp_path)


def test_inside_window_nothing_deleted(db: Session, doc: Doctor):
    """Marked 2 minutes ago — inside the 4-minute window. Nothing deleted."""
    tmp_path = f"./storage/audio/test_retention_{uuid.uuid4()}.wav"

    session, audio, note, transcript = _create_full_session(
        db, doc, SyncStatus.SUCCESS, marked_minutes_ago=2, tmp_path=tmp_path
    )

    deleted_count = RetentionWorker.run_cleanup()

    assert deleted_count == 0
    assert os.path.exists(tmp_path)

    db.refresh(audio)
    assert audio.deleted_at is None
    assert audio.file_path == tmp_path

    # Cleanup
    os.remove(tmp_path)


def test_idempotent_double_run(db: Session, doc: Doctor):
    """Running the job twice does not error on already-deleted artifacts."""
    tmp_path = f"./storage/audio/test_retention_{uuid.uuid4()}.wav"

    session, audio, note, transcript = _create_full_session(
        db, doc, SyncStatus.SUCCESS, marked_minutes_ago=10, tmp_path=tmp_path
    )

    count1 = RetentionWorker.run_cleanup()
    assert count1 == 1

    # Second run: file already gone, row already has deleted_at
    count2 = RetentionWorker.run_cleanup()
    assert count2 == 0  # No new deletions


def test_sync_success_transitions_to_finalized(db: Session, doc: Doctor):
    """EMR sync success path transitions session to FINALIZED and marks audio."""
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.STOPPED)
    session.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.stopped_at = datetime.now(timezone.utc) - timedelta(minutes=50)
    db.add(session)
    db.commit()
    db.refresh(session)

    audio = AudioMetadata(
        session_id=session.id,
        file_path=f"./storage/audio/test_finalize_{uuid.uuid4()}.wav",
        duration_seconds=120.5,
        format="audio/wav",
    )
    db.add(audio)

    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.SIGNED)
    db.add(note)
    db.commit()
    db.refresh(note)

    sig = Signature(soap_note_id=note.id, doctor_id=doc.id)
    section = SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="S")
    db.add_all([sig, section])
    db.commit()

    with patch("httpx.Client.post") as mock_post:
        mock_response = Response(201, json={"id": 1})
        mock_response.request = Request("POST", "http://test")
        mock_post.return_value = mock_response

        EMRSyncClient.sync_note_to_emr(note.id)

    db.refresh(session)
    assert session.status == SessionStatus.FINALIZED
    assert session.finalized_at is not None

    db.refresh(audio)
    assert audio.retention_marked_for_deletion_at is not None

    db.refresh(note)
    assert note.sync_status == SyncStatus.SUCCESS
    assert note.status == SOAPNoteStatus.SIGNED


def test_permission_error_skips_row_and_continues(db: Session, doc: Doctor):
    """If os.remove raises an OSError (e.g. PermissionError), the row is skipped but others are processed."""
    tmp_path1 = f"./storage/audio/test_retention_err1_{uuid.uuid4()}.wav"
    tmp_path2 = f"./storage/audio/test_retention_err2_{uuid.uuid4()}.wav"

    # Create two eligible artifacts
    session1, audio1, note1, transcript1 = _create_full_session(
        db, doc, SyncStatus.SUCCESS, marked_minutes_ago=10, tmp_path=tmp_path1
    )
    session2, audio2, note2, transcript2 = _create_full_session(
        db, doc, SyncStatus.SUCCESS, marked_minutes_ago=10, tmp_path=tmp_path2
    )

    with patch("os.remove") as mock_remove:
        # First call raises PermissionError, second call succeeds
        def side_effect(path):
            if path == tmp_path1:
                raise PermissionError("File in use")
            elif path == tmp_path2:
                # Do nothing, just return (simulating success)
                pass
            else:
                pass
        
        mock_remove.side_effect = side_effect
        
        deleted_count = RetentionWorker.run_cleanup()

        # Only one should have been marked as deleted
        assert deleted_count == 1

        db.refresh(audio1)
        # audio1 should NOT have deleted_at because it threw an error
        assert audio1.deleted_at is None
        assert audio1.file_path == tmp_path1

        db.refresh(audio2)
        # audio2 should be successfully processed
        assert audio2.deleted_at is not None
        assert audio2.file_path is None

    # Cleanup the physical files that were mocked away
    if os.path.exists(tmp_path1):
        os.remove(tmp_path1)
    if os.path.exists(tmp_path2):
        os.remove(tmp_path2)
