from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.session import ConsultationSession
from app.models.transcript import Transcript, TranscriptStatus, TranscriptSegment
from app.models.soap_note import SOAPNote, SOAPSection, SOAPNoteStatus, SOAPSectionType
from app.services.soap_service import SOAPService
from app.services.exceptions import SessionNotFoundError, SOAPValidationError, SOAPNoteAlreadySignedError, TranscriptNotReadyError, SOAPSectionNotFoundError

class SOAPNoteService:
    @staticmethod
    def generate_and_save_draft(db: Session, session_id: int, doctor_id: int) -> SOAPNote:
        # 1. Ownership Check
        session = db.query(ConsultationSession).filter(
            ConsultationSession.id == session_id,
            ConsultationSession.doctor_id == doctor_id
        ).first()
        
        if not session:
            raise SessionNotFoundError("Session not found or does not belong to the current doctor")

        # 2. Data Retrieval
        transcript = db.query(Transcript).filter(Transcript.session_id == session_id).first()
        if not transcript or transcript.status != TranscriptStatus.completed:
            raise TranscriptNotReadyError("Completed transcript not found or not ready for this session")

        segments_db = db.query(TranscriptSegment).filter(
            TranscriptSegment.transcript_id == transcript.id
        ).order_by(TranscriptSegment.start_time).all()

        segments = [
            {"speaker_role": seg.speaker_role, "text": seg.text}
            for seg in segments_db
        ]

        # 3. Generation
        draft_content = SOAPService.generate_draft(segments)

        # 4. Persistence
        existing_note = db.query(SOAPNote).filter(SOAPNote.session_id == session_id).first()
        if existing_note:
            if existing_note.status == SOAPNoteStatus.SIGNED:
                raise SOAPNoteAlreadySignedError("Cannot overwrite a signed clinical record.")
            # Delete old draft and its sections
            db.delete(existing_note)
            db.commit()

        note = SOAPNote(
            session_id=session_id,
            status=SOAPNoteStatus.DRAFT,
            created_at=datetime.now(timezone.utc)
        )
        db.add(note)
        db.flush() # flush to get note.id

        sections = []
        section_mapping = {
            SOAPSectionType.SUBJECTIVE: draft_content.get("subjective", ""),
            SOAPSectionType.OBJECTIVE: draft_content.get("objective", ""),
            SOAPSectionType.ASSESSMENT: draft_content.get("assessment", ""),
            SOAPSectionType.PLAN: draft_content.get("plan", ""),
        }

        for sec_type, text_content in section_mapping.items():
            # if somehow the generated text is missing, handle gracefully but require the section
            if text_content is None:
                text_content = ""
                
            sec = SOAPSection(
                soap_note_id=note.id,
                section_type=sec_type,
                content=text_content
            )
            sections.append(sec)
            db.add(sec)

        # 5. Validation Rule
        # Enforce exactly 4 SOAPSection rows per SOAPNote explicitly
        if len(sections) != 4:
            db.rollback()
            raise SOAPValidationError(f"Expected exactly 4 SOAP sections, got {len(sections)}")

        # Additional safety check against the generated output
        if not all(k in draft_content for k in ["subjective", "objective", "assessment", "plan"]):
            db.rollback()
            raise SOAPValidationError("Generated draft is missing required sections")

        db.commit()
        db.refresh(note)
        return note

    @staticmethod
    def update_section(db: Session, note_id: int, section_id: int, new_content: str) -> SOAPNote:
        note = db.query(SOAPNote).filter(SOAPNote.id == note_id).first()
        if not note:
            # We assume ownership is verified outside, so if it's missing here it's unexpected
            raise ValueError("SOAP note not found")
            
        if note.status == SOAPNoteStatus.SIGNED:
            raise SOAPNoteAlreadySignedError("Cannot edit a signed clinical record.")
            
        section = db.query(SOAPSection).filter(
            SOAPSection.id == section_id,
            SOAPSection.soap_note_id == note.id
        ).first()
        
        if not section:
            raise SOAPSectionNotFoundError("SOAP section not found or does not belong to this note")
            
        section.content = new_content
        note.last_edited_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(note)
        return note
