import logging
from typing import Dict, List, Any
from app.ml.whisper_engine import WhisperEngine

logger = logging.getLogger(__name__)

class ASRService:
    @staticmethod
    def transcribe_audio(audio_path: str) -> Dict[str, Any]:
        """
        Loads the singleton Whisper model and transcribes the audio file.
        Returns a dictionary:
        {
            "text": str,
            "segments": [
                {
                    "start": float,
                    "end": float,
                    "text": str
                },
                ...
            ]
        }
        Raises ASRError if transcription fails.
        """
        engine = WhisperEngine.get_instance()
        result = engine.transcribe(audio_path)
        
        segments = []
        for segment in result.get("segments", []):
            segments.append({
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text", "").strip()
            })
            
        return {
            "text": result.get("text", "").strip(),
            "segments": segments
        }

    @staticmethod
    def transcribe_and_diarize(session_id: int) -> None:
        """
        Background task that runs ASR and Diarization, and persists results.
        Opens its own database session from SessionLocal.
        """
        from datetime import datetime, timezone
        from app.db.session import SessionLocal
        from app.models.transcript import Transcript, TranscriptSegment, TranscriptStatus
        from app.models.audio import AudioMetadata
        from app.services.diarization_service import DiarizationService
        
        db = SessionLocal()
        try:
            # 1. Fetch audio metadata
            audio = db.query(AudioMetadata).filter(AudioMetadata.session_id == session_id).first()
            if not audio:
                raise ValueError("Audio metadata not found for session")

            transcript = db.query(Transcript).filter(Transcript.session_id == session_id).first()
            if not transcript:
                raise ValueError("Transcript record not found for session")

            # 2. Run transcription
            asr_result = ASRService.transcribe_audio(audio.file_path)
            
            # 3. Run diarization
            diarized = DiarizationService.diarize_segments(asr_result.get("segments", []))
            
            # 4. Clear any old segments (concurrency safety)
            db.query(TranscriptSegment).filter(TranscriptSegment.transcript_id == transcript.id).delete()
            
            # 5. Save segments
            for seg in diarized:
                db_seg = TranscriptSegment(
                    transcript_id=transcript.id,
                    speaker_role=seg["speaker_role"],
                    text=seg["text"],
                    start_time=seg["start"],
                    end_time=seg["end"]
                )
                db.add(db_seg)
                
            # 6. Finalize status
            transcript.status = TranscriptStatus.completed
            transcript.finalized_at = datetime.now(timezone.utc)
            db.commit()
            
        except Exception as e:
            db.rollback()
            logger.exception("Background ASR/Diarization failed for session %s", session_id)
            # Mark transcript as failed so it can be retried
            transcript = db.query(Transcript).filter(Transcript.session_id == session_id).first()
            if transcript:
                transcript.status = TranscriptStatus.failed
                db.commit()
        finally:
            db.close()


