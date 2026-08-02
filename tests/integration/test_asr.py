import os
import wave
import struct
import pytest
from app.ml.whisper_engine import WhisperEngine, ASRError
from app.services.asr_service import ASRService

TEST_AUDIO_DIR = "./storage/test_audio"

@pytest.fixture(scope="module", autouse=True)
def setup_test_directory():
    os.makedirs(TEST_AUDIO_DIR, exist_ok=True)
    yield
    # Clean up test directory files
    if os.path.exists(TEST_AUDIO_DIR):
        for f in os.listdir(TEST_AUDIO_DIR):
            try:
                os.remove(os.path.join(TEST_AUDIO_DIR, f))
            except OSError:
                pass
        try:
            os.rmdir(TEST_AUDIO_DIR)
        except OSError:
            pass

def create_dummy_wav(path: str, duration_sec: float = 1.0, sample_rate: int = 16000):
    num_samples = int(duration_sec * sample_rate)
    with wave.open(path, 'w') as wav_file:
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
        for _ in range(num_samples):
            data = struct.pack('<h', 0)
            wav_file.writeframesraw(data)

def test_transcribe_success():
    wav_path = os.path.join(TEST_AUDIO_DIR, "dummy_silence.wav")
    create_dummy_wav(wav_path, duration_sec=1.0)
    
    # Run the real Whisper service on it
    text = ASRService.transcribe_audio(wav_path)
    
    # Should run successfully and return empty or minimal text (since it's silence)
    assert isinstance(text, str)

def test_transcribe_corrupt_file():
    corrupt_path = os.path.join(TEST_AUDIO_DIR, "corrupt.wav")
    with open(corrupt_path, "w") as f:
        f.write("This is not a valid audio file.")
        
    with pytest.raises(ASRError):
        ASRService.transcribe_audio(corrupt_path)

def test_transcribe_nonexistent_file():
    with pytest.raises(ASRError) as exc_info:
        ASRService.transcribe_audio(os.path.join(TEST_AUDIO_DIR, "missing.wav"))
    assert "Audio file not found" in str(exc_info.value)
