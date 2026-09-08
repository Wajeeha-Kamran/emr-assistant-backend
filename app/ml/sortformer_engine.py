"""
NVIDIA NeMo Sortformer speaker diarization engine.

WHY THIS EXISTS
pyannote replaced the three home-built diarizers on 16 Aug 2026 and reached
88.3% word / 77.6% speaker accuracy across the four scripted consultations.
The mean hides the real problem: pyannote scored 100.0 / 12.4 / 98.1 / 100.0.
Script 2 is not a small regression, it is a total speaker swap — the two
voices in that recording are close enough in pitch that the clustering step
merged and mislabelled them, and every downstream SOAP section inherited the
wrong role.

Sortformer, measured on the same four recordings against the same reference
transcripts and the same scorer, scored 100.0 / 99.5 / 100.0 / 100.0.
It is an end-to-end model: it predicts speaker-labelled frames directly
instead of embedding-then-clustering, so there is no clustering step to
collapse. Script 2 goes from 12.4% to 99.5%.

    evidence: docs/evidence/benchmarks/diarizer_head_to_head.csv
              docs/evidence/benchmarks/sortformer_cpu_detail.csv
              docs/evidence/benchmarks/base_sortformer_detail.csv

Sortformer needs no Hugging Face token and no licence acceptance — the
checkpoint is openly downloadable, which also removes the three-gated-repo
trap documented in pyannote_engine.py.

REQUIREMENTS
    pip install nemo_toolkit[asr]        (3.0.0 verified)

NeMo 3.0.0, openai-whisper 20250625 and pyannote.audio 4.0.7 install and
import together in one Python 3.12 environment on Windows with numpy 2.5.2
and torch 2.14.0 — verified 8 Sep 2026. The earlier note that this needed
Linux or WSL2 was a consequence of Python 3.14 and of NeMo 2.5.0's numpy 1.x
pin, and no longer applies.

Sortformer expects MONO 16 kHz audio. Recordings arrive from the mobile
client at other rates, so the engine converts before inference rather than
trusting the caller.
"""

import logging
import os
import tempfile
import threading
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

MODEL_ID = "nvidia/diar_sortformer_4spk-v1"
TARGET_SR = 16000


class SortformerError(Exception):
    """Raised when the Sortformer pipeline is unavailable or fails."""


# Serialised for the same reason Whisper and pyannote are — one shared torch
# model is not safe to call from several threads at once, and FastAPI runs
# every endpoint handler in a worker threadpool.
_INFERENCE_LOCK = threading.Lock()


class SortformerEngine:
    _instance: Optional["SortformerEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        if SortformerEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access SortformerEngine.")

        try:
            from nemo.collections.asr.models import SortformerEncLabelModel
        except Exception as e:
            raise SortformerError(
                f"Could not import NeMo ({type(e).__name__}: {e}). "
                "Install it with: pip install nemo_toolkit[asr]"
            ) from e

        try:
            model = SortformerEncLabelModel.from_pretrained(MODEL_ID)
            model.eval()
        except Exception as e:
            raise SortformerError(
                f"Failed to load {MODEL_ID} ({type(e).__name__}: {e})."
            ) from e

        try:
            import torch
            if torch.cuda.is_available():
                model.to(torch.device("cuda"))
                logger.info("SortformerEngine using CUDA")
            else:
                logger.info("SortformerEngine using CPU")
        except Exception:  # pragma: no cover - device selection is best effort
            pass

        self.model = model

    @classmethod
    def get_instance(cls) -> "SortformerEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def diarize(self, audio_path: str, num_speakers: int = 2
                ) -> List[Tuple[float, float, str]]:
        """
        Returns [(start_seconds, end_seconds, speaker_label), ...] sorted by
        start time — the same shape PyannoteEngine.diarize returns, so
        DiarizationService can use either without knowing which is running.

        num_speakers is accepted for interface compatibility and ignored:
        Sortformer is a fixed 4-speaker model that emits only the speakers it
        actually finds. On two-person consultations it returns two.
        """
        prepared, cleanup = self._as_mono16k(audio_path)
        try:
            with _INFERENCE_LOCK:
                pred = self.model.diarize(audio=[prepared], batch_size=1)
        finally:
            if cleanup and os.path.exists(prepared):
                try:
                    os.remove(prepared)
                except OSError:  # pragma: no cover
                    pass

        turns = self._as_turns(pred)
        turns.sort(key=lambda t: t[0])

        speakers = {t[2] for t in turns}
        logger.info("Sortformer produced %d turns across %d speaker(s)",
                    len(turns), len(speakers))
        if len(speakers) < 2:
            logger.warning(
                "Sortformer found only %d speaker(s). The recording may "
                "contain one voice.", len(speakers)
            )
        return turns

    # ------------------------------------------------------------------

    @staticmethod
    def _as_turns(pred) -> List[Tuple[float, float, str]]:
        """
        Normalise NeMo's return value into (start, end, label) tuples.

        diarize() returns one entry per input file, and each entry is a list of
        segments. NeMo has emitted those segments both as "start end speaker"
        strings and as 3-tuples across releases, so both are accepted rather
        than pinning the toolkit to one version.
        """
        raw = pred[0] if isinstance(pred, (list, tuple)) and pred else pred
        turns: List[Tuple[float, float, str]] = []
        for s in raw:
            if isinstance(s, str):
                p = s.replace(",", " ").split()
                turns.append((float(p[0]), float(p[1]), str(p[2])))
            elif isinstance(s, (list, tuple)) and len(s) >= 3:
                turns.append((float(s[0]), float(s[1]), str(s[2])))
            else:
                raise SortformerError(
                    f"Unexpected Sortformer segment: {type(s).__name__} {s!r}")
        return turns

    @staticmethod
    def _as_mono16k(audio_path: str) -> Tuple[str, bool]:
        """
        Return (path_to_use, caller_must_delete_it).

        Audio already mono at 16 kHz is passed through untouched, so the common
        case costs one header read. Anything else is converted to a temporary
        WAV. soundfile is used rather than torchaudio for the reason recorded
        in pyannote_engine._load_waveform: torchcodec needs FFmpeg shared
        libraries that the ordinary Windows FFmpeg build does not ship.
        """
        import soundfile as sf

        info = sf.info(audio_path)
        if info.channels == 1 and info.samplerate == TARGET_SR:
            return audio_path, False

        audio, sr = sf.read(audio_path)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != TARGET_SR:
            import librosa
            audio = librosa.resample(
                audio.astype("float32"), orig_sr=sr, target_sr=TARGET_SR)

        fd, out = tempfile.mkstemp(suffix=".wav", prefix="sortformer_")
        os.close(fd)
        sf.write(out, audio, TARGET_SR, subtype="PCM_16")
        logger.debug("Converted %s (%d ch @ %d Hz) to mono 16 kHz",
                     audio_path, info.channels, info.samplerate)
        return out, True
