import os
import sys

# Add the project root to the sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.session import ConsultationSession, SessionStatus
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.models.audio import AudioMetadata
from app.models.transcript import Transcript, TranscriptSegment
from app.models.code_suggestion import CodeSuggestion
from app.services.code_suggester import CodeSuggesterService

def run():
    db = SessionLocal()
    try:
        # Create a test doctor if not exists
        doc = db.query(Doctor).filter_by(email="script_codesug@example.com").first()
        if not doc:
            doc = Doctor(email="script_codesug@example.com", hashed_password="pw", full_name="Script Doctor")
            db.add(doc)
            db.commit()
            db.refresh(doc)
            
        # Create session and note
        session = ConsultationSession(doctor_id=doc.id, status=SessionStatus.FINALIZED)
        db.add(session)
        db.commit()
        
        note = SOAPNote(session_id=session.id, status=SOAPNoteStatus.DRAFT)
        db.add(note)
        db.commit()
        
        # Add realistic sections
        db.add_all([
            SOAPSection(
                soap_note_id=note.id, 
                section_type=SOAPSectionType.SUBJECTIVE, 
                content="Patient complains of severe headache."
            ),
            SOAPSection(
                soap_note_id=note.id, 
                section_type=SOAPSectionType.OBJECTIVE, 
                content="Blood pressure 140/90. No focal neurological deficits."
            ),
            SOAPSection(
                soap_note_id=note.id, 
                section_type=SOAPSectionType.ASSESSMENT, 
                content="Patient presents with acute severe headache, likely tension-type or early migraine. Elevated blood pressure noted, possibly secondary to pain."
            ),
            SOAPSection(
                soap_note_id=note.id, 
                section_type=SOAPSectionType.PLAN, 
                content="Advised rest in a dark room. Take ibuprofen 400mg PRN. Monitor blood pressure at home. Follow up if symptoms worsen."
            )
        ])
        db.commit()
        
        print(f"\n--- Running CodeSuggesterService for Note ID {note.id} ---")
        suggestions = CodeSuggesterService.generate_suggestions(note.id, db)
        
        print("\n=== GENERATED SUGGESTIONS ===")
        for s in suggestions:
            print(f"Rank: {s.rank} | Code: {s.code} | Type: {s.code_type.value} | Confidence: {s.confidence_score:.4f} | Desc: {s.description}")
            
    finally:
        db.close()

if __name__ == "__main__":
    run()
