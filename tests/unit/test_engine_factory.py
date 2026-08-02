import pytest
from app.ml.engine_factory import get_asr_engine
from app.ml.whisper_engine import WhisperEngine
from app.ml.riva_engine import RivaEngine


def test_default_engine_is_whisper():
    """With ASR_ENGINE='whisper' (default), get_asr_engine() returns a WhisperEngine instance."""
    from app.core.config import settings
    assert settings.ASR_ENGINE == "whisper"
    engine = get_asr_engine()
    # WhisperEngine uses a singleton; the instance is already loaded by test_asr.py
    # so no model download occurs here.
    assert isinstance(engine, WhisperEngine)


def test_riva_engine_selected_and_raises(monkeypatch):
    """With ASR_ENGINE='riva', get_asr_engine() returns a RivaEngine instance
    and calling .transcribe() raises NotImplementedError."""
    from app.core import config as config_module
    monkeypatch.setattr(config_module.settings, "ASR_ENGINE", "riva")

    engine = get_asr_engine()
    assert isinstance(engine, RivaEngine)

    with pytest.raises(NotImplementedError):
        engine.transcribe("dummy_path.wav")
