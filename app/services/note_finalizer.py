from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import BackgroundTasks
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SyncStatus
from app.models.signature import Signature
from app.services.exceptions import SOAPNoteAlreadySignedError
from app.services.emr_sync_client import EMRSyncClient

class NoteFinalizerService:
    @staticmethod
    def sign_note(db: Session, note_id: int, doctor_id: int, background_tasks: BackgroundTasks) -> Signature:
        note = db.query(SOAPNote).filter(SOAPNote.id == note_id).first()
        if not note:
            raise ValueError("SOAP note not found")
            
        if note.status == SOAPNoteStatus.SIGNED:
            raise SOAPNoteAlreadySignedError("This SOAP note has already been signed.")
            
        note.status = SOAPNoteStatus.SIGNED
        note.sync_status = SyncStatus.PENDING
        
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
            
        background_tasks.add_task(EMRSyncClient.sync_note_to_emr, note.id)
        
        return signature
