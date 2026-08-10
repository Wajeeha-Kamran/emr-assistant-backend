from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.soap_note import SOAPNote, SOAPNoteStatus
from app.models.signature import Signature
from app.services.exceptions import SOAPNoteAlreadySignedError

class NoteFinalizerService:
    @staticmethod
    def sign_note(db: Session, note_id: int, doctor_id: int) -> Signature:
        note = db.query(SOAPNote).filter(SOAPNote.id == note_id).first()
        if not note:
            raise ValueError("SOAP note not found")
            
        if note.status == SOAPNoteStatus.SIGNED:
            raise SOAPNoteAlreadySignedError("This SOAP note has already been signed.")
            
        note.status = SOAPNoteStatus.SIGNED
        
        signature = Signature(
            soap_note_id=note.id,
            doctor_id=doctor_id
        )
        db.add(signature)
        
        try:
            db.commit()
            db.refresh(signature)
        except IntegrityError:
            db.rollback()
            raise SOAPNoteAlreadySignedError("This SOAP note has already been signed concurrently.")
            
        # TODO (Module 6.2): Trigger EMR sync logic here.
        # This acts as a stub to be implemented later when the real EMR service is integrated.
        
        return signature
