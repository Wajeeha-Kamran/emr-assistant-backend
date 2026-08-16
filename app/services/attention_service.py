"""
Which of a doctor's consultations did not finish, and what to do about each.

A consultation passes through: record -> transcribe -> generate note -> sign ->
sync. Every stage can be interrupted, and none of them recovers on its own. A
stuck consultation is not merely inconvenient: the retention worker deletes
audio only when its note is both SIGNED and SUCCESS, so anything stuck here
keeps a recording of a patient's voice on disk indefinitely.

Nothing else in the API enumerates a doctor's consultations, so without this
service a stuck one is unreachable from the client.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audio import AudioMetadata
from app.models.doctor import Doctor
from app.models.session import ConsultationSession
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SyncStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.attention import AttentionAction, AttentionItem, AttentionReason

ACTION_FOR_REASON = {
    AttentionReason.TRANSCRIPT_FAILED: AttentionAction.RESUME_TRANSCRIPTION,
    AttentionReason.TRANSCRIPT_STALLED: AttentionAction.RESUME_TRANSCRIPTION,
    AttentionReason.NOTE_NOT_GENERATED: AttentionAction.GENERATE_NOTE,
    AttentionReason.NOT_SIGNED: AttentionAction.SIGN_NOTE,
    AttentionReason.SYNC_FAILED: AttentionAction.RETRY_SYNC,
}


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive timestamp as UTC.

    Every timestamp column is declared timezone-aware, so this should never
    fire against PostgreSQL. It exists so a comparison cannot raise TypeError
    if a row is ever written by something that dropped the offset.
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AttentionService:

    @staticmethod
    def asr_deadline(transcript: Transcript, audio: Optional[AudioMetadata]) -> datetime:
        """The moment after which a transcript still in `processing` cannot be running.

        ASRService gives itself max(ASR_TIMEOUT_FLOOR_SECONDS, duration *
        ASR_TIMEOUT_FACTOR) and marks the transcript failed when that elapses.
        The same budget is reused here rather than inventing a second number,
        plus a buffer for the commit that follows a timeout.

        So a transcript still `processing` past this point was not timed out by
        the service — it was abandoned, which happens when the process dies
        mid-job. Background tasks live in the API process and nothing resumes
        them on restart.
        """
        duration = (audio.duration_seconds if audio else 0.0) or 0.0
        budget = max(
            settings.ASR_TIMEOUT_FLOOR_SECONDS,
            int(duration * settings.ASR_TIMEOUT_FACTOR),
        )
        return _aware(transcript.created_at) + timedelta(
            seconds=budget + settings.ATTENTION_STALL_BUFFER_SECONDS
        )

    @staticmethod
    def is_stalled(
        transcript: Optional[Transcript],
        audio: Optional[AudioMetadata],
        now: Optional[datetime] = None,
    ) -> bool:
        if transcript is None or transcript.status != TranscriptStatus.processing:
            return False
        now = now or datetime.now(timezone.utc)
        return now > AttentionService.asr_deadline(transcript, audio)

    @staticmethod
    def collect(db: Session, doctor: Doctor) -> List[AttentionItem]:
        """Return this doctor's stuck consultations, newest consultation first.

        One row per session: a session has at most one transcript, one note and
        one audio record, each enforced by a unique constraint.
        """
        now = datetime.now(timezone.utc)
        grace_cutoff = now - timedelta(minutes=settings.ATTENTION_GRACE_MINUTES)

        rows = (
            db.query(ConsultationSession, Transcript, SOAPNote, AudioMetadata)
            .select_from(ConsultationSession)
            .outerjoin(Transcript, Transcript.session_id == ConsultationSession.id)
            .outerjoin(SOAPNote, SOAPNote.session_id == ConsultationSession.id)
            .outerjoin(AudioMetadata, AudioMetadata.session_id == ConsultationSession.id)
            .filter(ConsultationSession.doctor_id == doctor.id)
            .all()
        )

        items: List[AttentionItem] = []

        def emit(session, reason, note=None):
            items.append(
                AttentionItem(
                    session_id=session.id,
                    note_id=note.id if note else None,
                    reason=reason,
                    action=ACTION_FOR_REASON[reason],
                    created_at=session.created_at,
                    last_edited_at=note.last_edited_at if note else None,
                )
            )

        for session, transcript, note, audio in rows:
            # --- after a note exists -------------------------------------
            if note is not None:
                if note.sync_status == SyncStatus.FAILED:
                    emit(session, AttentionReason.SYNC_FAILED, note)
                elif (
                    note.status == SOAPNoteStatus.DRAFT
                    and _aware(note.created_at) <= grace_cutoff
                ):
                    # Inside the grace window this is the note being written
                    # right now, not an abandoned one.
                    emit(session, AttentionReason.NOT_SIGNED, note)
                continue

            # --- before a note exists ------------------------------------
            if transcript is None:
                # Recording was started but never stopped, so no audio was
                # stored and no transcript row was created. There is nothing
                # to resume and nothing on disk to clean up.
                continue

            if transcript.status == TranscriptStatus.failed:
                emit(session, AttentionReason.TRANSCRIPT_FAILED)
            elif AttentionService.is_stalled(transcript, audio, now):
                emit(session, AttentionReason.TRANSCRIPT_STALLED)
            elif transcript.status == TranscriptStatus.completed:
                finished = _aware(transcript.finalized_at) or _aware(transcript.created_at)
                if finished <= grace_cutoff:
                    # The transcript is ready but no note was ever generated.
                    # Generation is triggered by the client, so this is a
                    # consultation the doctor walked away from mid-review.
                    emit(session, AttentionReason.NOTE_NOT_GENERATED)

        items.sort(key=lambda item: item.created_at, reverse=True)
        return items
