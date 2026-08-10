import pytest
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.models.code_suggestion import CodeSuggestion
from app.services.code_suggester import CodeSuggesterService, SOAPNoteAlreadySignedError
from app.db.session import SessionLocal
from app.models.doctor import Doctor

@pytest.fixture
def test_data():
    db = SessionLocal()
    doc = Doctor(email="test_codesug@example.com", hashed_password="pw", full_name="Test Doctor")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    yield db, doc
    db.close()

def test_generate_suggestions_success(test_data):
    db_session, test_doctor = test_data
    # Setup session & note
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)
    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    # Add sections with clinical content
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.SUBJECTIVE, content="Patient complains of ankle pain."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.OBJECTIVE, content="Swelling observed."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Patient twisted their right ankle while playing basketball. Swelling and tenderness observed."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Rest, ice, compress, elevate.")
    ])
    db_session.commit()
    
    # Generate
    suggestions = CodeSuggesterService.generate_suggestions(note.id, db_session)
    
    # Verify 10 generated (5 ICD10, 5 CPT)
    assert len(suggestions) == 10
    assert all(isinstance(s, CodeSuggestion) for s in suggestions)
    assert all(s.accepted is False for s in suggestions)
    assert all(s.soap_note_id == note.id for s in suggestions)
    
    ranks = [s.rank for s in suggestions]
    assert ranks == list(range(1, 11))
    
    # Assert AT LEAST ONE ICD10 and AT LEAST ONE CPT
    icd10_codes = [s for s in suggestions if s.code_type.value == "ICD10"]
    cpt_codes = [s for s in suggestions if s.code_type.value == "CPT"]
    assert len(icd10_codes) == 5
    assert len(cpt_codes) == 5
    
    # Check that they were persisted
    persisted = db_session.query(CodeSuggestion).filter_by(soap_note_id=note.id).order_by(CodeSuggestion.rank).all()
    assert len(persisted) == 10
    assert persisted[0].code.startswith("S93.4")  # Matches ankle sprain variants
    
def test_generate_suggestions_empty_note(test_data):
    db_session, test_doctor = test_data
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)
    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    # Empty Assessment/Plan
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Not documented in dialogue."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="   ")
    ])
    db_session.commit()
    
    suggestions = CodeSuggesterService.generate_suggestions(note.id, db_session)
    assert len(suggestions) == 0
    assert db_session.query(CodeSuggestion).filter_by(soap_note_id=note.id).count() == 0

def test_regenerate_draft_deletes_old_suggestions(test_data):
    db_session, test_doctor = test_data
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)
    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Headache."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Take Tylenol.")
    ])
    db_session.commit()
    
    # Generate first time
    CodeSuggesterService.generate_suggestions(note.id, db_session)
    assert db_session.query(CodeSuggestion).filter_by(soap_note_id=note.id).count() == 10
    
    # Generate second time
    CodeSuggesterService.generate_suggestions(note.id, db_session)
    
    # Should still be 10, not 20
    assert db_session.query(CodeSuggestion).filter_by(soap_note_id=note.id).count() == 10

def test_regenerate_signed_raises_error_and_keeps_old(test_data):
    db_session, test_doctor = test_data
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)

    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Headache."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Take Tylenol.")
    ])
    db_session.commit()
    
    # Generate
    initial_suggestions = CodeSuggesterService.generate_suggestions(note.id, db_session)
    assert len(initial_suggestions) == 10
    
    # Mark as signed
    note.status = SOAPNoteStatus.SIGNED
    db_session.commit()
    
    # Try to regenerate
    with pytest.raises(SOAPNoteAlreadySignedError):
        CodeSuggesterService.generate_suggestions(note.id, db_session)
        
    # Verify original 5 are intact
    assert db_session.query(CodeSuggestion).filter_by(soap_note_id=note.id).count() == 10

def test_generate_suggestions_single_section_only(test_data):
    db_session, test_doctor = test_data
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)
    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    # Only Assessment has content
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Patient twisted their right ankle while playing basketball. Swelling and tenderness observed."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Not documented in dialogue.")
    ])
    db_session.commit()
    
    suggestions = CodeSuggesterService.generate_suggestions(note.id, db_session)
    
    # Should only generate 5 ICD10 codes
    assert len(suggestions) == 5
    assert all(s.code_type.value == "ICD10" for s in suggestions)
    ranks = [s.rank for s in suggestions]
    assert ranks == [1, 2, 3, 4, 5]

def test_rank_ordering_sequential_no_gaps(test_data):
    from unittest.mock import patch
    from app.models.code_reference import CodeType, CodeReference
    
    db_session, test_doctor = test_data
    session = ConsultationSession(doctor_id=test_doctor.id, status=SessionStatus.FINALIZED)
    db_session.add(session)
    db_session.commit()
    
    note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
    db_session.add(note)
    db_session.commit()
    
    db_session.add_all([
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.ASSESSMENT, content="Headache."),
        SOAPSection(soap_note_id=note.id, section_type=SOAPSectionType.PLAN, content="Rest.")
    ])
    db_session.commit()
    
    # Mock return values for search_codes
    mock_icd10 = [(CodeReference(code=f"I{i}", description=f"ICD{i}", code_type=CodeType.ICD10), 0.9) for i in range(3)]
    mock_cpt = [(CodeReference(code=f"C{i}", description=f"CPT{i}", code_type=CodeType.CPT), 0.8) for i in range(5)]
    
    def side_effect(text, top_k, code_type):
        if code_type == CodeType.ICD10:
            return mock_icd10
        elif code_type == CodeType.CPT:
            return mock_cpt
        return []

    with patch('app.services.code_reference_service.CodeReferenceService.search_codes', side_effect=side_effect):
        suggestions = CodeSuggesterService.generate_suggestions(note.id, db_session)
        
        assert len(suggestions) == 8
        ranks = [s.rank for s in suggestions]
        assert ranks == [1, 2, 3, 4, 5, 6, 7, 8]
        
        # Verify first CPT result gets rank 4
        cpt_suggestions = [s for s in suggestions if s.code_type == CodeType.CPT]
        assert cpt_suggestions[0].rank == 4
