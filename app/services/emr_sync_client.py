import httpx
import logging
import time
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.soap_note import SOAPNote, SyncStatus
from app.models.session import SessionStatus
from app.core.config import settings
from app.services.session_manager import SessionManager
from app.services.retention_service import RetentionService
from app.core.metrics import metrics

logger = logging.getLogger(__name__)

class EMRSyncClient:
    @staticmethod
    def sync_note_to_emr(note_id: int):
        db = SessionLocal()
        try:
            note = db.query(SOAPNote).filter(SOAPNote.id == note_id).first()
            if not note:
                logger.error(f"Cannot sync note {note_id}: not found")
                return
                
            session = note.session
            
            # Calculate duration
            audio_meta = session.audio
            duration_val = 0.0
            if audio_meta:
                duration_val = audio_meta.duration_seconds
            else:
                if session.started_at and session.stopped_at:
                    duration_val = (session.stopped_at - session.started_at).total_seconds()
            
            duration = int(duration_val) # Explicitly cast to int to prevent 422
                    
            accepted_codes = [
                {
                    "code": c.code,
                    "description": c.description,
                    "code_type": c.code_type.value,
                    "rank": c.rank,
                    "accepted": c.accepted
                }
                for c in note.suggestions if c.accepted
            ]
            
            sections = {s.section_type.value: s.content for s in note.sections}
            
            # Handle nullable session timestamps
            # This fallback only occurs for notes not produced by the normal record/stop flow 
            # (e.g. manually generated or tests).
            if not session.started_at or not session.stopped_at:
                logger.warning(f"Note {note.id} lacks proper session timestamps; fabricating start/stop using note.created_at")
            
            started = session.started_at.isoformat() if session.started_at else note.created_at.isoformat()
            stopped = session.stopped_at.isoformat() if session.stopped_at else note.created_at.isoformat()
            
            # Fetch doctor
            from app.models.doctor import Doctor
            doctor = db.query(Doctor).filter(Doctor.id == session.doctor_id).first()
            doctor_name = doctor.full_name if doctor else "Unknown Doctor"
            
            payload = {
                "source_session_id": session.id,
                "source_soap_note_id": note.id,
                "session": {
                    "started_at": started,
                    "stopped_at": stopped,
                    "duration_seconds": duration
                },
                "content": {
                    "sections": sections,
                    "code_suggestions": accepted_codes,
                    "signature": {
                        "doctor_id": note.signature.doctor_id,
                        "doctor_name": doctor_name,
                        "signed_at": note.signature.signed_at.isoformat(),
                        "method": note.signature.method
                    }
                }
            }
            
            max_retries = 3
            try:
                with httpx.Client(timeout=10.0) as client:
                    for attempt in range(1, max_retries + 1):
                        try:
                            response = client.post(
                                f"{settings.SIMULATED_EMR_URL}/simulated-emr/records",
                                json=payload
                            )
                            
                            if response.is_error:
                                if 400 <= response.status_code < 500:
                                    # Fail fast on 4xx — log status code and body length only.
                                    # Response body may contain clinical text (e.g. FastAPI 422
                                    # echoes the offending input value), so never log its content.
                                    logger.error(f"EMR sync 4xx error for note {note_id}: {response.status_code} (body {len(response.text)} chars)")
                                    break
                                
                            response.raise_for_status()
                            
                            # 4. Success -> Finalize session and note
                            note.sync_status = SyncStatus.SUCCESS
                            db.commit()
                            
                            # Transition session to FINALIZED, which also marks audio for cleanup
                            try:
                                SessionManager.transition_state(db, session, SessionStatus.FINALIZED)
                                RetentionService.mark_audio_for_cleanup(db, session.id, commit=True)
                            except Exception as e:
                                # logger.error — if finalization fails, audio is never flagged and therefore
                                # orphaned, but the sync itself succeeded and we don't want to report FAILED.
                                logger.error(f"Post-sync finalization failed for note {note_id}: {e}")
                                
                            metrics.record_metric("emr_sync", True)
                            return
                        
                        except httpx.RequestError as e:
                            logger.error(f"EMR sync request error for note {note_id}: {e}")
                        except httpx.HTTPStatusError as e:
                            logger.error(f"EMR sync HTTP error for note {note_id}: {e}")
                            
                        if attempt < max_retries:
                            time.sleep(2 ** attempt)  # simple backoff
                            
                # If we exit the loop, all retries failed or we broke early on a 4xx
                note.sync_status = SyncStatus.FAILED
                db.commit()
                metrics.record_metric("emr_sync", False)
                
            except Exception as e:
                logger.error(f"Failed to sync note {note_id}: {e}", exc_info=True)
                note.sync_status = SyncStatus.FAILED
                db.commit()
                metrics.record_metric("emr_sync", False)
            
        except Exception as e:
            logger.error(f"Failed to sync note {note_id}: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
