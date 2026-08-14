import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.audio import AudioMetadata
from app.models.session import ConsultationSession
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SyncStatus
from app.core.config import settings

logger = logging.getLogger(__name__)

class RetentionWorker:
    @staticmethod
    def run_cleanup() -> int:
        """
        Scans for audio artifacts past the retention window and deletes the physical
        audio files from AUDIO_STORAGE_DIR. Keeps the audio_metadata row intact for
        the audit trail: sets deleted_at and clears file_path.

        Deliberately does NOT touch:
        - Transcripts or transcript segments: the extractive SOAP design makes the
          transcript the provenance record proving note content was derived from real
          speech and never fabricated. Deleting it would destroy that evidence chain.
        - SOAPNote, SOAPSection, Signature, CodeSuggestion: clinical record integrity.

        Returns the number of artifacts deleted in this sweep.
        """
        db = SessionLocal()
        deleted_count = 0
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=settings.RETENTION_WINDOW_MINUTES)
            
            eligible = (
                db.query(AudioMetadata)
                .join(ConsultationSession, AudioMetadata.session_id == ConsultationSession.id)
                .join(SOAPNote, SOAPNote.session_id == ConsultationSession.id)
                .filter(
                    # 1. Note is SIGNED
                    SOAPNote.status == SOAPNoteStatus.SIGNED,
                    # 2. Note is successfully synced to EMR
                    SOAPNote.sync_status == SyncStatus.SUCCESS,
                    # 3. Audio has been flagged for deletion
                    AudioMetadata.retention_marked_for_deletion_at.isnot(None),
                    # 4. Retention window has elapsed
                    AudioMetadata.retention_marked_for_deletion_at <= cutoff_time,
                    # 5. Not already deleted
                    AudioMetadata.deleted_at.is_(None),
                )
                .all()
            )
            
            for audio in eligible:
                file_path = audio.file_path
                session_id = audio.session_id
                
                # Look up note id for logging
                note = db.query(SOAPNote).filter(SOAPNote.session_id == session_id).first()
                note_id = note.id if note else "unknown"
                
                # Delete the physical file
                file_deleted = True
                if file_path:
                    try:
                        os.remove(file_path)
                        logger.info(
                            f"Retention: deleted audio file | session={session_id} "
                            f"note={note_id} path={file_path} at={datetime.now(timezone.utc).isoformat()}"
                        )
                    except FileNotFoundError:
                        # File already gone — idempotent, log and continue
                        logger.info(
                            f"Retention: audio file already absent | session={session_id} "
                            f"note={note_id} path={file_path}"
                        )
                    except OSError as e:
                        logger.error(
                            f"Retention: failed to delete audio file | session={session_id} "
                            f"note={note_id} path={file_path} error={e}"
                        )
                        file_deleted = False
                
                # Update the audit trail only if the file was deleted (or already absent)
                if file_deleted:
                    audio.deleted_at = datetime.now(timezone.utc)
                    audio.file_path = None
                    deleted_count += 1
                
                # Commit per row to avoid a single failure rolling back everything
                db.commit()
                
        except Exception as e:
            logger.error(f"Retention worker error: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
            
        if deleted_count > 0:
            logger.info(f"Retention sweep complete: {deleted_count} artifact(s) deleted")
        
        return deleted_count
