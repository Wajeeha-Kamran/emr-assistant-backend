from app.ml.asr_engine import ASRError


class RivaEngine:
    """
    Placeholder for NVIDIA Riva ASR integration (Module 2.4 stub).

    Implements the ASREngine protocol interface structurally — no explicit
    inheritance required. Real Riva SDK integration is deferred to a later
    phase per the project roadmap (Phase 8.3 / Module 2.4 extension).

    To activate this engine, set ASR_ENGINE=riva in your .env file.
    """

    def transcribe(self, audio_path: str) -> dict:
        """
        Not yet implemented.

        Raises:
            NotImplementedError: Always. Switch to ASR_ENGINE=whisper for a
                working transcription engine.
        """
        raise NotImplementedError(
            "RivaEngine is not yet implemented. "
            "Set ASR_ENGINE=whisper in your .env to use the Whisper engine."
        )
