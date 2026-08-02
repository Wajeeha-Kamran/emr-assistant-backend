from app.ml.whisper_engine import WhisperEngine

class ASRService:
    @staticmethod
    def transcribe_audio(audio_path: str) -> str:
        """
        Loads the singleton Whisper model and transcribes the audio file.
        Returns the raw consolidated text from transcription.
        Raises ASRError if transcription fails.
        """
        engine = WhisperEngine.get_instance()
        result = engine.transcribe(audio_path)
        return result.get("text", "").strip()
