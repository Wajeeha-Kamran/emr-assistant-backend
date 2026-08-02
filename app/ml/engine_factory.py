from app.ml.asr_engine import ASREngine
from app.core.config import settings


def get_asr_engine() -> ASREngine:
    """
    Returns the configured ASR engine instance.

    Engine selection is controlled by the ASR_ENGINE config setting (default: "whisper").
    To switch engines, set ASR_ENGINE in your .env file:
        ASR_ENGINE=whisper   — Whisper (openai-whisper), CPU/GPU, English-only
        ASR_ENGINE=riva      — NVIDIA Riva (stub; not yet implemented)

    Returns:
        An object satisfying the ASREngine protocol.
    """
    if settings.ASR_ENGINE == "riva":
        from app.ml.riva_engine import RivaEngine
        return RivaEngine()

    # Default: Whisper singleton (loaded once at first call)
    from app.ml.whisper_engine import WhisperEngine
    return WhisperEngine.get_instance()
