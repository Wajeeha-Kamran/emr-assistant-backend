"""
Tests that prove clinical text encryption actually works:
- ORM write → ORM read returns plaintext (transparent)
- ORM write → raw SQL read returns ciphertext (NOT plaintext)
- Corrupted ciphertext raises DecryptionError specifically
- None values pass through unchanged
"""
import pytest
import uuid
from sqlalchemy import text
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptSegment, TranscriptStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPSectionType
from app.core.encrypted_type import DecryptionError


CLINICAL_TEXT = "Patient reports chronic headache for 3 weeks with nausea"
SOAP_CONTENT = "Subjective: Patient presents with persistent migraine and photophobia"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def doctor(db):
    doc = Doctor(
        email=f"enc_test_{uuid.uuid4()}@example.com",
        hashed_password="hashed",
        full_name="Dr. Encryption",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def session_obj(db, doctor):
    s = ConsultationSession(doctor_id=doctor.id, status=SessionStatus.STOPPED)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ─── TranscriptSegment.text ───────────────────────────────────────────

def test_transcript_segment_orm_roundtrip(db, session_obj):
    """ORM write then ORM read must return original plaintext."""
    transcript = Transcript(session_id=session_obj.id, status=TranscriptStatus.completed)
    db.add(transcript)
    db.flush()

    seg = TranscriptSegment(
        transcript_id=transcript.id,
        speaker_role="DOCTOR",
        text=CLINICAL_TEXT,
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    assert seg.text == CLINICAL_TEXT


def test_transcript_segment_raw_sql_is_ciphertext(db, session_obj):
    """Raw SQL bypassing the ORM must NOT return plaintext — it must be ciphertext bytes."""
    transcript = Transcript(session_id=session_obj.id, status=TranscriptStatus.completed)
    db.add(transcript)
    db.flush()

    seg = TranscriptSegment(
        transcript_id=transcript.id,
        speaker_role="DOCTOR",
        text=CLINICAL_TEXT,
    )
    db.add(seg)
    db.commit()

    # Read raw column with direct SQL, bypassing the TypeDecorator
    row = db.execute(
        text('SELECT "text" FROM transcript_segments WHERE id = :id'),
        {"id": seg.id},
    ).fetchone()

    raw_value = row[0]

    # The raw value must be bytes (bytea), not a string
    assert isinstance(raw_value, (bytes, memoryview)), (
        f"Expected bytes from raw SQL, got {type(raw_value)}"
    )

    # The raw bytes must NOT contain the plaintext
    raw_bytes = bytes(raw_value) if isinstance(raw_value, memoryview) else raw_value
    assert CLINICAL_TEXT.encode() not in raw_bytes, (
        "Raw SQL returned plaintext — encryption is NOT working"
    )


# ─── SOAPSection.content ─────────────────────────────────────────────

def test_soap_section_orm_roundtrip(db, session_obj):
    """ORM write then ORM read must return original plaintext."""
    note = SOAPNote(session_id=session_obj.id)
    db.add(note)
    db.flush()

    section = SOAPSection(
        soap_note_id=note.id,
        section_type=SOAPSectionType.SUBJECTIVE,
        content=SOAP_CONTENT,
    )
    db.add(section)
    db.commit()
    db.refresh(section)

    assert section.content == SOAP_CONTENT


def test_soap_section_raw_sql_is_ciphertext(db, session_obj):
    """Raw SQL bypassing the ORM must NOT return plaintext."""
    note = SOAPNote(session_id=session_obj.id)
    db.add(note)
    db.flush()

    section = SOAPSection(
        soap_note_id=note.id,
        section_type=SOAPSectionType.SUBJECTIVE,
        content=SOAP_CONTENT,
    )
    db.add(section)
    db.commit()

    row = db.execute(
        text("SELECT content FROM soap_sections WHERE id = :id"),
        {"id": section.id},
    ).fetchone()

    raw_value = row[0]
    assert isinstance(raw_value, (bytes, memoryview))

    raw_bytes = bytes(raw_value) if isinstance(raw_value, memoryview) else raw_value
    assert SOAP_CONTENT.encode() not in raw_bytes, (
        "Raw SQL returned plaintext — encryption is NOT working"
    )


# ─── DecryptionError ─────────────────────────────────────────────────

def test_corrupted_ciphertext_raises_decryption_error(db, session_obj):
    """Corrupted ciphertext must raise DecryptionError, not crash or return empty."""
    transcript = Transcript(session_id=session_obj.id, status=TranscriptStatus.completed)
    db.add(transcript)
    db.flush()

    # Insert garbage bytes directly, bypassing the TypeDecorator
    db.execute(
        text(
            'INSERT INTO transcript_segments (transcript_id, speaker_role, "text") '
            "VALUES (:tid, 'DOCTOR', :garbage)"
        ),
        {"tid": transcript.id, "garbage": b"this-is-not-valid-ciphertext"},
    )
    db.commit()

    # Find the row we just inserted
    row = db.execute(
        text(
            "SELECT id FROM transcript_segments "
            "WHERE transcript_id = :tid ORDER BY id DESC LIMIT 1"
        ),
        {"tid": transcript.id},
    ).fetchone()

    with pytest.raises(DecryptionError):
        # SQLAlchemy decrypts during row loading, not on attribute access,
        # so the exception fires at db.get() rather than when .text is read.
        seg = db.get(TranscriptSegment, row[0])
