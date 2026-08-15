import os
import threading

import whisper
import torch
from app.core.config import settings
from app.ml.asr_engine import ASRError  # noqa: F401 — re-exported for backward compatibility


# ---------------------------------------------------------------------------
# Whisper is NOT thread-safe when a single loaded model is shared.
#
# Evidence (Module 8.3 load test, 10 concurrent sessions, 15 Aug 2026):
# every concurrent request failed inside whisper/model.py with either
#     KeyError: Linear(in_features=512, out_features=512, bias=True)
#         at  v = kv_cache[self.value]
# or
#     RuntimeError: cannot reshape tensor of 0 elements into shape [1, 0, 8, -1]
#
# Cause: whisper attaches a per-decode key/value cache to the model instance
# via forward hooks (install_kv_cache_hooks). Concurrent decodes on the SAME
# model object therefore share and clobber that scratch state — one thread
# clears entries another is still reading.
#
# Fix: serialise inference. Requests queue instead of colliding. This costs
# throughput, not correctness, and satisfies the SRS 2.3.3 requirement to
# "support at least 10 concurrent doctor sessions without failure".
#
# Deliberately NOT Celery/Redis: the failure is thread contention on one
# process-local object, not a task-distribution problem. A lock is the
# proportionate fix and keeps Module 10.1's container setup simple.
#
# Timeout interaction: callers time the whole call, so time spent queueing
# counts toward the ASR budget. That budget is max(ASR_TIMEOUT_FLOOR_SECONDS,
# duration * ASR_TIMEOUT_FACTOR) — with factor 6 there is ample headroom
# (10 concurrent 10-minute consultations queue in ~800s against a 3600s
# budget), so no timeout change is required.
# ---------------------------------------------------------------------------
_INFERENCE_LOCK = threading.Lock()


class WhisperEngine:
    _instance = None
    _instance_lock = threading.Lock()

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
        # Double-checked locking: without it, two threads arriving together on
        # a cold start would each load a ~150MB model and one would be orphaned.
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribes the given audio file using Whisper.
        Locks the language to English ('en').
        Raises ASRError if the file is unreadable or transcription fails.

        Thread safety: inference is serialised on a module-level lock. Only one
        transcription runs at a time across the whole process. See the comment
        at the top of this module for the evidence behind that decision.
        """
        if not os.path.exists(audio_path):
            raise ASRError(f"Audio file not found: {audio_path}")

        try:
            with _INFERENCE_LOCK:
                # We explicitly specify language="en" as required
                result = self.model.transcribe(audio_path, language="en")
            return result
        except Exception as e:
            # Wrapping any transcription/ffmpeg errors in a clean ASRError
            raise ASRError(f"ASR transcription failed: {e}") from e
