"""
pyannote.audio speaker diarization engine.

WHY THIS EXISTS
Three home-built approaches were measured against four scripted consultations
on 15 Aug 2026 and none reached the SRS's 85% target:

    pause heuristic            68.9%   never fired at any threshold; the
                                       score is simply the proportion of
                                       words the doctor happens to speak
    per-segment fingerprints   66.0%   fails when Whisper puts two speakers
                                       in one segment
    sliding-window fingerprints 48.8%  good turn structure (15 turns found
                                       against 16 real) but fragile
                                       clustering and label assignment

pyannote.audio is a purpose-built diarization pipeline: voice activity
detection, speaker embeddings, clustering and overlap handling, developed and
evaluated together on conversational speech. Module 2.2's revision note
named it as the upgrade to make if measured accuracy fell short. It did.

Requires a Hugging Face token with the licences accepted for THREE gated
repositories, not two. Loading pyannote/speaker-diarization-3.1 under
pyannote.audio 4.x pulls its component checkpoints from
pyannote/speaker-diarization-community-1, so all of these must be accepted:

    pyannote/segmentation-3.0
    pyannote/speaker-diarization-3.1
    pyannote/speaker-diarization-community-1

The third is not mentioned in the error message the first two produce, and
cost a debugging cycle here. It is recorded so nobody repeats it.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MODEL_ID = "pyannote/speaker-diarization-3.1"


class PyannoteError(Exception):
    """Raised when the diarization pipeline is unavailable or fails."""


# Serialised for the same reason Whisper is — one shared torch model is not
# safe to call from several threads at once. See whisper_engine.py.
_INFERENCE_LOCK = threading.Lock()


class PyannoteEngine:
    _instance: Optional["PyannoteEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        if PyannoteEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access PyannoteEngine.")

        from app.core.config import settings

        token = getattr(settings, "HF_TOKEN", "") or ""
        if not token:
            raise PyannoteError(
                "HF_TOKEN is not set in .env. Create a read token at "
                "huggingface.co/settings/tokens and accept the licences for "
                "pyannote/segmentation-3.0 and pyannote/speaker-diarization-3.1."
            )

        try:
            from pyannote.audio import Pipeline
        except Exception as e:
            raise PyannoteError(
                f"Could not import pyannote.audio ({type(e).__name__}: {e}). "
                "Install it with: pip install pyannote.audio"
            ) from e

        # The keyword changed across pyannote versions (use_auth_token -> token).
        # Try the current name first, then the legacy one, rather than pinning
        # the library to one release.
        pipeline = None
        errors: List[str] = []
        for kwargs in ({"token": token}, {"use_auth_token": token}):
            try:
                pipeline = Pipeline.from_pretrained(MODEL_ID, **kwargs)
                break
            except TypeError as e:
                errors.append(f"{list(kwargs)[0]}: {e}")
            except Exception as e:
                errors.append(f"{list(kwargs)[0]}: {type(e).__name__}: {e}")

        if pipeline is None:
            raise PyannoteError(
                "Failed to load the diarization pipeline. Most often this means "
                "the model licences have not been accepted on huggingface.co, or "
                "the token lacks read access. Details: " + " | ".join(errors)
            )

        try:
            import torch
            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))
                logger.info("PyannoteEngine using CUDA")
            else:
                logger.info("PyannoteEngine using CPU")
        except Exception:  # pragma: no cover - device selection is best effort
            pass

        self.pipeline = pipeline

    @classmethod
    def get_instance(cls) -> "PyannoteEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def diarize(self, audio_path: str, num_speakers: int = 2
                ) -> List[Tuple[float, float, str]]:
        """
        Returns [(start_seconds, end_seconds, speaker_label), ...] sorted by
        start time. num_speakers is fixed at 2 — a consultation has exactly a
        doctor and a patient, and telling the pipeline so is far more reliable
        than letting it estimate the count from short audio.
        """
        audio = self._load_waveform(audio_path)

        with _INFERENCE_LOCK:
            result = self.pipeline(audio, num_speakers=num_speakers)

        annotation = self._as_annotation(result)

        turns = [
            (float(segment.start), float(segment.end), str(label))
            for segment, _, label in annotation.itertracks(yield_label=True)
        ]
        turns.sort(key=lambda t: t[0])

        speakers = {t[2] for t in turns}
        logger.info("pyannote produced %d turns across %d speaker(s)",
                    len(turns), len(speakers))
        if len(speakers) < 2:
            logger.warning(
                "pyannote found only %d speaker(s). The recording may contain "
                "one voice, or the two voices may be very similar.", len(speakers)
            )
        return turns

    @staticmethod
    def _load_waveform(audio_path: str) -> Dict[str, Any]:
        """
        Read the audio ourselves and hand pyannote a waveform, not a file path.

        WHY, because this looks like unnecessary work:
        pyannote.audio 4.x decodes audio through torchcodec, which loads
        FFmpeg's shared libraries at runtime. On Windows that requires the
        "full-shared" FFmpeg build; the ordinary release everyone installs is
        static and ships no DLLs, so torchcodec fails with

            RuntimeError: Could not load libtorchcodec
            FileNotFoundError: Could not find module libtorchcodec_core9.dll

        Observed here on Windows with torch 2.13.0+cpu. The library documents
        this exact escape hatch in its own warning message: supply audio
        in-memory as {"waveform": (channel, time) Tensor, "sample_rate": int}
        and the decoder is never called.

        soundfile is used for the read because it is already a dependency and
        links libsndfile directly, with no FFmpeg involvement. Resampling is
        left to pyannote, which does it internally with torchaudio.
        """
        try:
            import soundfile as sf
            import torch
        except Exception as e:
            raise PyannoteError(
                f"Could not import the audio reader ({type(e).__name__}: {e}). "
                "Install it with: pip install soundfile"
            ) from e

        try:
            data, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        except Exception as e:
            raise PyannoteError(
                f"Could not read audio {audio_path} ({type(e).__name__}: {e}). "
                "soundfile handles WAV, FLAC and OGG; other containers must be "
                "converted first."
            ) from e

        # soundfile returns (time, channel); pyannote requires (channel, time).
        waveform = torch.from_numpy(data.T.copy())
        return {
            "waveform": waveform,
            "sample_rate": int(sample_rate),
            "uri": Path(audio_path).stem,
        }

    @staticmethod
    def _as_annotation(result):
        """
        Normalise the pipeline's return value into a pyannote.core.Annotation.

        pyannote.audio 3.x returned an Annotation directly. 4.x returns a
        DiarizeOutput dataclass instead unless the pipeline was built with
        legacy=True — verified in pyannote/audio/pipelines/speaker_diarization.py
        of the installed 4.0.7:

            def apply(...) -> DiarizeOutput | Annotation

        Calling .itertracks() on a DiarizeOutput raises AttributeError, which
        the diarization service would swallow as a generic failure and fall
        back to the weaker window method. Accepting both shapes removes that
        trap and keeps the engine working across the version boundary.

        exclusive_speaker_diarization is preferred over speaker_diarization
        because it has overlapping speech removed; the library documents it as
        "adapted to downstream transcription", which is exactly this use — each
        transcribed word must be attributed to exactly one speaker.
        """
        if hasattr(result, "itertracks"):
            return result

        for attr in ("exclusive_speaker_diarization", "speaker_diarization"):
            candidate = getattr(result, attr, None)
            if candidate is not None and hasattr(candidate, "itertracks"):
                logger.debug("Using DiarizeOutput.%s", attr)
                return candidate

        raise PyannoteError(
            f"Unrecognised diarization result of type {type(result).__name__}; "
            "expected a pyannote.core.Annotation or a DiarizeOutput."
        )
