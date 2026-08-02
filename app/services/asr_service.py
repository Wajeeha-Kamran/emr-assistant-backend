from typing import Dict, List, Any
from app.ml.whisper_engine import WhisperEngine

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

