import os
import whisper
import torch
from app.core.config import settings

class ASRError(Exception):
    """Custom exception raised when ASR transcription fails."""
    pass

class WhisperEngine:
    _instance = None

    def __init__(self) -> None:
        if WhisperEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access WhisperEngine.")
        
        # Check for GPU (cuda), fallback to CPU
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Load the model once
        try:
            self.model = whisper.load_model(settings.WHISPER_MODEL_NAME, device=self.device)
        except Exception as e:
            raise ASRError(f"Failed to load Whisper model '{settings.WHISPER_MODEL_NAME}': {e}") from e

    @classmethod
    def get_instance(cls) -> "WhisperEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribes the given audio file using Whisper.
        Locks the language to English ('en').
        Raises ASRError if the file is unreadable or transcription fails.
        """
        if not os.path.exists(audio_path):
            raise ASRError(f"Audio file not found: {audio_path}")

        try:
            # We explicitly specify language="en" as required
            result = self.model.transcribe(audio_path, language="en")
            return result
        except Exception as e:
            # Wrapping any transcription/ffmpeg errors in a clean ASRError
            raise ASRError(f"ASR transcription failed: {e}") from e
