from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.session import ConsultationSession, SessionStatus
from app.models.audio import AudioMetadata

class RetentionService:
    @staticmethod
    def mark_audio_for_cleanup(db: Session, session_id: int, commit: bool = True) -> AudioMetadata | None:
        """
        Flags the session's audio metadata as eligible for deletion.
        Strictly restricted to FINALIZED sessions.
        Raises ValueError if session is not found or is in an invalid lifecycle state.
        """
        session = db.query(ConsultationSession).filter(ConsultationSession.id == session_id).first()
        if not session:
            raise ValueError("Session not found")
            
        if session.status != SessionStatus.FINALIZED:
            raise ValueError(
                f"Cannot mark audio for cleanup: Session is in {session.status} state, must be FINALIZED."
            )
            
        audio = db.query(AudioMetadata).filter(AudioMetadata.session_id == session_id).first()
        if not audio:
            return None
            
        if audio.retention_marked_for_deletion_at is None:
            audio.retention_marked_for_deletion_at = datetime.now(timezone.utc)
            if commit:
                db.commit()
                db.refresh(audio)
            
        return audio
