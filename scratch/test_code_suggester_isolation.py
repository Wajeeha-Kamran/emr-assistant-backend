import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.services.code_suggester import CodeSuggesterService
from app.services.code_reference_service import CodeReferenceService
from app.models.code_reference import CodeReference
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.models.session import ConsultationSession, SessionStatus
from app.models.audio import AudioMetadata
from app.models.transcript import Transcript, TranscriptSegment
from app.models.doctor import Doctor
from sqlalchemy import select

def run():
    db = SessionLocal()
    try:
        print("\n--- 1. EXACT Concatenated String Passed to search_codes() ---")
        
        # We recreate the exact logic CodeSuggesterService uses on the exact text
        sections = [
            SOAPSection(section_type=SOAPSectionType.ASSESSMENT, content="Patient presents with acute severe headache, likely tension-type or early migraine. Elevated blood pressure noted, possibly secondary to pain."),
            SOAPSection(section_type=SOAPSectionType.PLAN, content="Advised rest in a dark room. Take ibuprofen 400mg PRN. Monitor blood pressure at home. Follow up if symptoms worsen.")
        ]
        
        search_text_parts = []
        for sec in sections:
            content = sec.content.strip()
            if content and content != "Not documented in dialogue.":
                search_text_parts.append(f"{sec.section_type.value.capitalize()}: {content}")
                
        search_text = " ".join(search_text_parts)
        print(f"SEARCH_TEXT:\n{search_text}\n")
        
        print("\n--- 2. Call CodeReferenceService.search_codes() directly ---")
        test_phrase = "The patient's blood pressure is elevated, indicating possible hypertension."
        print(f"Querying: {test_phrase}")
        results = CodeReferenceService.get_instance().search_codes(test_phrase, top_k=5)
        for code, score in results:
            print(f"Code: {code.code} | Type: {code.code_type.value} | Confidence: {score:.4f} | Desc: {code.description}")
            
        print("\n--- 3. Confirm code_reference table rows ---")
        total_rows = db.query(CodeReference).count()
        print(f"Total rows in code_reference: {total_rows}")
        
        target_codes = db.query(CodeReference).filter(CodeReference.code.in_(['R51.9', 'I10'])).all()
        for c in target_codes:
            print(f"Found Code: {c.code} | Desc: {c.description}")
            
    finally:
        db.close()

if __name__ == "__main__":
    run()
