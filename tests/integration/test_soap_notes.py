import pytest
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.transcript import Transcript, TranscriptStatus, TranscriptSegment
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.services.soap_note_service import SOAPNoteService
from app.services.exceptions import SessionNotFoundError, SOAPValidationError, SOAPNoteAlreadySignedError
from unittest.mock import patch

@pytest.fixture
def test_data():
    db = SessionLocal()
    
    doc = Doctor(email="doc_soap@example.com", hashed_password="pw", full_name="Test Doctor")
    db.add(doc)
    db.commit()
    
    session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
    db.add(session)
    db.commit()
    
    transcript = Transcript(session_id=session.id, status=TranscriptStatus.completed)
    db.add(transcript)
    db.commit()
    
    # Add a mock segment to the transcript
    segment = TranscriptSegment(
        transcript_id=transcript.id,
        speaker_role="PATIENT",
        text="I have a headache.",
        start_time=0.0,
        end_time=5.0
    )
    db.add(segment)
    db.commit()
    db.refresh(doc)
    db.refresh(session)
    db.refresh(transcript)
    
    yield db, doc, session, transcript
    
    db.close()


def test_generate_and_save_draft_success(test_data):
    db, doc, session, _ = test_data
    
    note = SOAPNoteService.generate_and_save_draft(db, session.id, doc.id)
    assert note is not None
    assert note.session_id == session.id
    assert note.status == SOAPNoteStatus.DRAFT
    
    sections = db.query(SOAPSection).filter(SOAPSection.soap_note_id == note.id).all()
    assert len(sections) == 4
    
    types = {sec.section_type for sec in sections}
    assert types == {
        SOAPSectionType.SUBJECTIVE,
        SOAPSectionType.OBJECTIVE,
        SOAPSectionType.ASSESSMENT,
        SOAPSectionType.PLAN
    }


def test_ownership_check(test_data):
    db, doc, session, _ = test_data
    invalid_doctor_id = doc.id + 999
    
    with pytest.raises(SessionNotFoundError):
        SOAPNoteService.generate_and_save_draft(db, session.id, invalid_doctor_id)


def test_enforce_four_sections(test_data):
    db, doc, session, _ = test_data
    
    with patch("app.services.soap_service.SOAPService.generate_draft") as mock_gen:
        # Mock returns only 3 sections instead of 4
        mock_gen.return_value = {
            "subjective": "Headache",
            "objective": "No signs",
            "assessment": "Migraine"
            # Missing "plan"
        }
        
        with pytest.raises(SOAPValidationError):
            SOAPNoteService.generate_and_save_draft(db, session.id, doc.id)
            
        # Verify it wasn't persisted
        note = db.query(SOAPNote).filter(SOAPNote.session_id == session.id).first()
        assert note is None


def test_prevent_signed_note_overwrite(test_data):
    db, doc, session, _ = test_data
    
    # Pre-create a signed note
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.SIGNED)
    db.add(note)
    db.commit()
    
    with pytest.raises(SOAPNoteAlreadySignedError):
        SOAPNoteService.generate_and_save_draft(db, session.id, doc.id)
