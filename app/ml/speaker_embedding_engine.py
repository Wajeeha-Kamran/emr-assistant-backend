"""
Voice-embedding engine for speaker diarization.

WHY THIS EXISTS
The original diarization heuristic alternated speakers whenever the gap
between two Whisper segments exceeded a threshold. Measured against four
scripted consultations on 15 Aug 2026, it never alternated once:

    93 inter-segment gaps measured
    min 0.000s | mean 0.006s | max 0.560s
    flips at every threshold from 0.01s to 2.0s : 1, against ~66 real
    speaker changes

Whisper does not leave gaps between segments — silence is absorbed inside
segment boundaries — so the condition was structurally unreachable at any
threshold. Every transcript was labelled DOCTOR, which also left every SOAP
Subjective section empty, since that section is populated from PATIENT
segments.

This engine replaces pause-counting with something that actually listens:
each segment's audio is converted into a 256-dimension voice fingerprint,
and the fingerprints are grouped into two clusters.

Model: Resemblyzer (GE2E speaker encoder), ~17 MB, CPU-friendly, no gated
download and no account required.
"""

import logging
import sys
import threading
import types
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class SpeakerEmbeddingError(Exception):
    """Raised when voice embedding fails for a recoverable reason."""


def _ensure_pkg_resources() -> None:
    """
    Compatibility shim for a dead dependency chain.

    Resemblyzer imports webrtcvad, which does `import pkg_resources` purely to
    read its own version string. setuptools 81+ removed pkg_resources, so the
    import fails with ModuleNotFoundError on modern environments (observed
    here with setuptools 83 on Python 3.14).

    A minimal stand-in is installed rather than pinning setuptools backwards,
    which would constrain the whole project for one legacy version lookup.
    Only applied when pkg_resources is genuinely absent.
    """
    try:
        import pkg_resources  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    class _Distribution:
        version = "0.0.0"

    shim = types.ModuleType("pkg_resources")
    shim.get_distribution = lambda name: _Distribution()          # type: ignore[attr-defined]
    shim.resource_filename = lambda package, name: name            # type: ignore[attr-defined]
    shim.DistributionNotFound = Exception                          # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = shim
    logger.debug("Installed a minimal pkg_resources shim for webrtcvad.")


# Inference is serialised for the same reason Whisper's is — a single shared
# torch model is not safe to call from multiple threads. See whisper_engine.py.
_INFERENCE_LOCK = threading.Lock()

SAMPLE_RATE = 16000
# Resemblyzer needs roughly this much audio to produce a stable fingerprint.
MIN_SEGMENT_SECONDS = 0.4


class SpeakerEmbeddingEngine:
    _instance: Optional["SpeakerEmbeddingEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        if SpeakerEmbeddingEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access SpeakerEmbeddingEngine.")

        _ensure_pkg_resources()

        try:
            from resemblyzer import VoiceEncoder
        except Exception as e:
            # Report the ACTUAL failure. An earlier version of this file raised a
            # fixed "not installed" message, which masked a real import error and
            # cost a debugging cycle. Never replace a diagnostic with a guess.
            raise SpeakerEmbeddingError(
                f"Could not import resemblyzer ({type(e).__name__}: {e}). "
                "If it is not installed, run: pip install resemblyzer"
            ) from e

        try:
            self.encoder = VoiceEncoder()  # uses CUDA automatically if present
        except Exception as e:
            raise SpeakerEmbeddingError(f"Failed to load the voice encoder: {e}") from e
        logger.info("SpeakerEmbeddingEngine initialised")

    @classmethod
    def get_instance(cls) -> "SpeakerEmbeddingEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # -- audio ------------------------------------------------------------

    @staticmethod
    def load_audio(audio_path: str) -> np.ndarray:
        """
        Load an audio file into a 16 kHz float waveform, PRESERVING THE TIMELINE.

        Deliberately does NOT use resemblyzer.preprocess_wav. That function calls
        trim_long_silences() unconditionally, which physically removes silence
        from the waveform and therefore shifts every subsequent sample earlier.
        Whisper's segment timestamps refer to the ORIGINAL audio, so slicing a
        de-silenced waveform by those timestamps returns the wrong audio, with
        the error accumulating through the file.

        Measured consequence (15 Aug 2026), before this was fixed:
            script 1  (86.9s)  speaker accuracy 56.4%
            script 2  (73.4s)  speaker accuracy 65.2%
            script 3  (77.6s)  speaker accuracy 68.1%
            script 4 (135.7s)  speaker accuracy 16.1%   <- longest file, worst
        Sub-50% on a two-way choice means the labels had inverted entirely.

        Volume normalisation is kept — it does not alter timing.
        """
        _ensure_pkg_resources()
        try:
            import librosa
            from resemblyzer.audio import normalize_volume
            from resemblyzer.hparams import sampling_rate, audio_norm_target_dBFS

            wav, _ = librosa.load(str(audio_path), sr=sampling_rate)
            return normalize_volume(wav, audio_norm_target_dBFS, increase_only=True)
        except Exception as e:
            raise SpeakerEmbeddingError(
                f"Could not read audio {audio_path} ({type(e).__name__}: {e})"
            ) from e

    def embed_slice(self, wav: np.ndarray, start: float, end: float) -> Optional[np.ndarray]:
        """
        Fingerprint one time slice. Returns None when the slice is too short
        to be meaningful, so the caller can inherit a neighbouring label
        rather than clustering on noise.
        """
        a = max(0, int(start * SAMPLE_RATE))
        b = min(len(wav), int(end * SAMPLE_RATE))
        if b - a < int(MIN_SEGMENT_SECONDS * SAMPLE_RATE):
            return None
        with _INFERENCE_LOCK:
            emb = self.encoder.embed_utterance(wav[a:b])
        norm = np.linalg.norm(emb)
        return emb / norm if norm else None


# -- clustering -----------------------------------------------------------

def cluster_into_two(embeddings: np.ndarray) -> np.ndarray:
    """
    Split voice fingerprints into two speakers.

    Uses agglomerative clustering with average linkage over cosine distance.
    An earlier hand-rolled two-means proved fragile: on one recording every
    window collapsed into a single cluster, producing one "turn" for the whole
    consultation. Agglomerative clustering is deterministic, needs no
    initialisation strategy, and handles unbalanced speaker time far better.

    scikit-learn is already present as a librosa dependency, so this adds
    nothing to the install footprint.
    """
    n = len(embeddings)
    if n < 2:
        return np.zeros(n, dtype=int)

    try:
        from sklearn.cluster import AgglomerativeClustering
        model = AgglomerativeClustering(
            n_clusters=2, metric="cosine", linkage="average"
        )
        labels = model.fit_predict(embeddings).astype(int)
    except Exception as e:  # pragma: no cover - fallback path
        logger.warning("Agglomerative clustering unavailable (%s); using two-means.", e)
        labels = _two_means(embeddings)

    a = embeddings[labels == 0]
    b = embeddings[labels == 1]
    if len(a) and len(b):
        ca = a.mean(axis=0); ca /= (np.linalg.norm(ca) or 1)
        cb = b.mean(axis=0); cb /= (np.linalg.norm(cb) or 1)
        separation = float(ca @ cb)
        logger.info("Speaker cluster separation: centroid similarity %.3f "
                    "(%d vs %d windows)", separation, len(a), len(b))
        if separation > 0.95:
            logger.warning(
                "Speaker clusters are very weakly separated (%.3f). The two "
                "voices may be genuinely hard to distinguish.", separation
            )
    return labels


def _two_means(embeddings: np.ndarray, max_iter: int = 25) -> np.ndarray:
    """Deterministic two-means fallback, seeded by the least similar pair."""
    sim = embeddings @ embeddings.T
    i, j = np.unravel_index(np.argmin(sim), sim.shape)
    centroids = np.stack([embeddings[i], embeddings[j]])
    labels = np.zeros(len(embeddings), dtype=int)
    for step in range(max_iter):
        new_labels = (embeddings @ centroids.T).argmax(axis=1)
        if step > 0 and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for k in (0, 1):
            members = embeddings[labels == k]
            if len(members):
                v = members.mean(axis=0)
                nv = np.linalg.norm(v)
                if nv:
                    centroids[k] = v / nv
    return labels
