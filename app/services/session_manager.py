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
    def transition_state(db: Session, session: ConsultationSession, target_state: SessionStatus) -> ConsultationSession:
        valid_transitions = {
            SessionStatus.INITIATED: [SessionStatus.RECORDING],
            SessionStatus.RECORDING: [SessionStatus.STOPPED],
            SessionStatus.STOPPED: [SessionStatus.FINALIZED],
            SessionStatus.FINALIZED: []
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
            
        db.commit()
        db.refresh(session)
        return session
