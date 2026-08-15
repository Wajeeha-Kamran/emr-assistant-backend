import logging
from typing import Dict, Any
from app.ml.engine_factory import get_asr_engine

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
        engine = get_asr_engine()
        result = engine.transcribe(audio_path)
        
        segments = []
        for segment in result.get("segments", []):
            segments.append({
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text", "").strip(),
                # Word timestamps feed window-based diarization. Kept out of
                # the persisted transcript; used only during processing.
                "words": segment.get("words") or []
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

            # 2. Run transcription with dynamic timeout
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
            from app.core.config import settings
            from app.core.metrics import metrics
            
            duration = audio.duration_seconds or 0.0
            timeout = max(
                settings.ASR_TIMEOUT_FLOOR_SECONDS,
                int(duration * settings.ASR_TIMEOUT_FACTOR)
            )
            logger.info(f"ASR timeout budget for session {session_id} (duration {duration}s) computed as {timeout}s")
            
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(ASRService.transcribe_audio, audio.file_path)
                try:
                    asr_result = future.result(timeout=timeout)
                    metrics.record_metric("asr", True)
                except FuturesTimeoutError:
                    metrics.record_metric("asr", False)
                    logger.warning(f"ASR transcription for session {session_id} timed out after {timeout}s. Underlying thread continues.")
                    # Note: Since this runs in a BackgroundTask, a timeout marks the transcript failed. 
                    # The recovery path is the POST /transcripts/{session_id}/retry endpoint.
                    raise TimeoutError(f"ASR computation exceeded budget of {timeout}s")
                except Exception:
                    metrics.record_metric("asr", False)
                    raise
            finally:
                executor.shutdown(wait=False)

            
            # 3. Run diarization
            try:
                diarized = DiarizationService.diarize_segments(asr_result.get("segments", []), audio.file_path)
                metrics.record_metric("diarization", True)
            except Exception:
                metrics.record_metric("diarization", False)
                raise
            
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


