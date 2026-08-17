from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.session import ConsultationSession, SessionStatus

class SessionManager:
    @staticmethod
    def create_session(db: Session, doctor_id: int) -> ConsultationSession:
        db_session = ConsultationSession(
            doctor_id=doctor_id,
            status=SessionStatus.INITIATED
        )
        db.add(db_session)
        db.commit()
        db.refresh(db_session)
        return db_session

    @staticmethod
    def transition_state(db: Session, session: ConsultationSession, target_state: SessionStatus, commit: bool = True) -> ConsultationSession:
        # DISCARDED is reachable only from the two states that hold no audio.
        # STOPPED is deliberately excluded: by then the recording has been
        # uploaded, so the consultation has clinical content and belongs to the
        # attention list, not to a discard path.
        valid_transitions = {
            SessionStatus.INITIATED: [SessionStatus.RECORDING, SessionStatus.DISCARDED],
            SessionStatus.RECORDING: [SessionStatus.STOPPED, SessionStatus.DISCARDED],
            SessionStatus.STOPPED: [SessionStatus.FINALIZED],
            SessionStatus.FINALIZED: [],
            SessionStatus.DISCARDED: []
        }
        
        if target_state not in valid_transitions[session.status]:
            raise ValueError(f"Illegal state transition from {session.status} to {target_state}")
        
        session.status = target_state
        now = datetime.now(timezone.utc)
        
        if target_state == SessionStatus.RECORDING:
            session.started_at = now
        elif target_state == SessionStatus.STOPPED:
            session.stopped_at = now
        elif target_state == SessionStatus.FINALIZED:
            session.finalized_at = now
        elif target_state == SessionStatus.DISCARDED:
            session.discarded_at = now
            
        if commit:
            db.commit()
            db.refresh(session)
        return session
