"""
Shared machinery for the six model combinations.

WHY THE COMBINATIONS ARE SEPARATE FILES
Each combination is one file so the configuration for a run is visible in one
place and can be quoted directly in the report. Everything below the
configuration is identical between them and lives here, because six copies of
the same pipeline would drift apart the first time one was edited.

WHY EACH RUNS AS ITS OWN PROCESS
WhisperEngine and PyannoteEngine are singletons that read their settings once,
at construction. Changing the Whisper model size inside a single process after
the engine has loaded does nothing. Running one combination per process makes
the model size an ordinary configuration value again, and it also keeps a crash
in one combination from taking the others with it.

WHAT IS HELD CONSTANT
Only the pieces named in the combination change. Both diarizers are fed through
the same downstream code - the same word collection, the same smoothing, the
same question-count vote for which speaker is the doctor - so a difference in
the scores is a difference between the diarizers and not between two ways of
assembling their output.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Run from anywhere: scripts/combinations/x.py -> repository root on sys.path.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AUDIO_DIR = os.path.join(ROOT, "docs", "evidence", "human_distinct")
SCRIPTS_MD = os.path.join(ROOT, "docs", "evidence", "consultation_scripts.md")
RESULTS_DIR = os.path.join(ROOT, "docs", "evidence", "combinations")
TARGET = 85.0


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass
class Combination:
    """One row of the comparison table."""
    number: int
    asr: str                      # "whisper" | "parakeet"
    asr_model: str                # "base.en", "medium", "nvidia/parakeet-tdt-0.6b-v2"
    diarizer: str                 # "pyannote" | "sortformer"
    why: str                      # why this combination is being tested
    noise_db: Optional[int] = None   # SNR in dB, or None for clean audio
    hyper: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        base = f"{self.asr}:{self.asr_model} + {self.diarizer}"
        return base + (f" @ {self.noise_db} dB" if self.noise_db is not None else "")

    @property
    def needs_nemo(self) -> bool:
        return self.asr == "parakeet" or self.diarizer == "sortformer"


NEMO_ON_WINDOWS = """
This combination needs NVIDIA NeMo, which does not import on Windows.

Measured on 22 August 2026, Python 3.14, this laptop:
  - NeMo declares protobuf~=5.29.5; onnx requires protobuf 6.x. Protobuf
    enforces a matching major version, so one of the two must give.
  - NeMo reaches texterrors, which imports plac, which calls
    multiprocessing.get_context("fork") at import time. fork is a Unix system
    call. plac 1.4.6 needs it; plac 1.3.5 avoids it but imports asyncore,
    removed from Python in 3.12. No version satisfies both.

Sortformer itself is fine: 12 s for a 95 s consultation on this CPU, 0.13x
realtime. The obstacle is packaging, not the model.

Run this combination in the Colab notebook instead - see
docs/evidence/combinations/README.md. NVIDIA's supported routes on Windows are
WSL2 or a Linux container.
"""


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

def consultation_files() -> List[Tuple[int, str]]:
    """[(script number, path)] for consult_1.wav .. consult_4.wav."""
    found = []
    for n in range(1, 5):
        path = os.path.join(AUDIO_DIR, f"consult_{n}.wav")
        if os.path.exists(path):
            found.append((n, path))
    if not found:
        sys.exit(f"FATAL: no consult_*.wav under {AUDIO_DIR}")
    return found


def add_noise(path: str, snr_db: int, out_dir: str) -> str:
    """Write a copy with white noise mixed in at the given signal-to-noise ratio.

    The noise is generated from a fixed seed so the same combination run twice
    produces the same audio. Without that, a difference between two runs could
    be the noise rather than the model, and the comparison would be worthless.
    """
    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    rng = np.random.default_rng(seed=1234 + snr_db)
    signal_power = float(np.mean(audio ** 2))
    if signal_power <= 0:
        return path
    noise_power = signal_power / (10 ** (snr_db / 10.0))
    noise = rng.normal(0.0, float(np.sqrt(noise_power)), size=audio.shape).astype("float32")
    noisy = np.clip(audio + noise, -1.0, 1.0)

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(path))[0]}_snr{snr_db}.wav")
    sf.write(out, noisy, rate)
    return out


# --------------------------------------------------------------------------
# Speech recognition
# --------------------------------------------------------------------------

def transcribe_whisper(path: str, model_name: str) -> List[Dict[str, Any]]:
    """Whisper, through the project's own engine so the settings match the backend."""
    from app.core.config import settings
    settings.WHISPER_MODEL_NAME = model_name   # read when the engine is constructed
    from app.services.asr_service import ASRService
    return ASRService.transcribe_audio(path)["segments"]


def transcribe_parakeet(path: str, model_name: str) -> List[Dict[str, Any]]:
    """NVIDIA Parakeet, shaped to look like Whisper's output.

    The downstream diarization works at word level, so word timestamps are
    requested rather than segment ones. A segment without words would fall back
    to whole-segment labelling and quietly measure something else.
    """
    try:
        from nemo.collections.asr.models import ASRModel
    except Exception as exc:
        sys.exit(f"{NEMO_ON_WINDOWS}\nImport error was: {type(exc).__name__}: {exc}")

    model = ASRModel.from_pretrained(model_name)
    model.eval()
    output = model.transcribe([path], timestamps=True)
    first = output[0]

    stamps = getattr(first, "timestamp", None) or {}
    words = [
        {"word": w.get("word", ""), "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))}
        for w in stamps.get("word", [])
    ]
    segments = []
    for seg in stamps.get("segment", []) or []:
        s, e = float(seg.get("start", 0.0)), float(seg.get("end", 0.0))
        segments.append({
            "start": s, "end": e,
            "text": seg.get("segment", "").strip(),
            "words": [w for w in words if s <= w["start"] < e],
        })
    if not segments:
        text = getattr(first, "text", "") or str(first)
        segments = [{
            "start": words[0]["start"] if words else 0.0,
            "end": words[-1]["end"] if words else 0.0,
            "text": text.strip(),
            "words": words,
        }]
    return segments


# --------------------------------------------------------------------------
# Speaker separation
# --------------------------------------------------------------------------

def sortformer_turns(path: str) -> List[Tuple[float, float, str]]:
    """Sortformer, returned in pyannote's shape: [(start, end, label)].

    Returning the same shape is the point. Both diarizers then go through the
    project's own word labelling, smoothing and doctor identification, so the
    comparison isolates the diarizer.
    """
    try:
        from nemo.collections.asr.models import SortformerEncLabelModel
    except Exception as exc:
        sys.exit(f"{NEMO_ON_WINDOWS}\nImport error was: {type(exc).__name__}: {exc}")

    model = SortformerEncLabelModel.from_pretrained("nvidia/diar_sortformer_4spk-v1")
    model.eval()
    predictions = model.diarize(audio=[path], batch_size=1)

    turns: List[Tuple[float, float, str]] = []
    for line in predictions[0]:
        parts = str(line).split()
        if len(parts) >= 3:
            turns.append((float(parts[0]), float(parts[1]), parts[2]))
    turns.sort(key=lambda t: t[0])
    return turns


def diarize(segments: List[Dict[str, Any]], path: str, method: str) -> List[Dict[str, Any]]:
    from app.services.diarization_service import DiarizationService

    if method == "pyannote":
        from app.core.config import settings
        settings.DIARIZATION_METHOD = "pyannote"
        return DiarizationService.diarize_segments(segments, path)

    if method != "sortformer":
        raise ValueError(f"unknown diarizer: {method}")

    turns = sortformer_turns(path)
    if not turns:
        raise ValueError("Sortformer returned no speaker turns")

    words = DiarizationService._collect_words(segments)
    if not words:
        raise ValueError("no word timestamps; cannot label at word level")

    labels = [DiarizationService._label_for(w["start"], w["end"], turns) for w in words]
    labels = DiarizationService._smooth(labels)
    doctor_label = DiarizationService._identify_doctor(words, labels)
    return DiarizationService._group(words, labels, doctor_label)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def score(script_number: int, produced: List[Dict[str, Any]]) -> Dict[str, float]:
    """Word and speaker accuracy against the written script, using the
    project's existing metrics so these numbers sit beside the earlier ones."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from evaluate_accuracy import (parse_scripts, normalise, strip_numerics,
                                   word_error_rate, speaker_accuracy)

    scripts = parse_scripts(SCRIPTS_MD)
    if script_number not in scripts:
        raise KeyError(f"script {script_number} not in {SCRIPTS_MD}")

    ref_words, ref_spk = [], []
    for speaker, text in scripts[script_number]:
        for w in normalise(text):
            ref_words.append(w)
            ref_spk.append(speaker)

    hyp_words, hyp_spk = [], []
    for seg in produced:
        for w in normalise(seg.get("text", "")):
            hyp_words.append(w)
            hyp_spk.append(seg.get("speaker_role", ""))

    wer = word_error_rate(ref_words, hyp_words)
    wer_nonum = word_error_rate(strip_numerics(ref_words), strip_numerics(hyp_words))
    correct, total = speaker_accuracy(ref_words, ref_spk, hyp_words, hyp_spk)

    return {
        "word_accuracy": round((1 - wer) * 100, 1),
        "word_accuracy_no_numerals": round((1 - wer_nonum) * 100, 1),
        "speaker_accuracy": round(correct / total * 100, 1) if total else 0.0,
        "words_compared": total,
    }


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run(combo: Combination) -> Dict[str, Any]:
    print("=" * 70)
    print(f"Combination {combo.number}: {combo.label}")
    print(f"  {combo.why}")
    print("=" * 70)
    for key, value in combo.hyper.items():
        print(f"  {key:24s} {value}")
    print()

    if combo.needs_nemo:
        try:
            import nemo  # noqa: F401
        except Exception as exc:
            sys.exit(f"{NEMO_ON_WINDOWS}\nImport error was: {type(exc).__name__}: {exc}")

    transcriber: Callable[[str, str], List[Dict[str, Any]]] = (
        transcribe_whisper if combo.asr == "whisper" else transcribe_parakeet
    )

    rows: List[Dict[str, Any]] = []
    noise_dir = os.path.join(RESULTS_DIR, "noisy_audio")

    for number, path in consultation_files():
        audio_path = add_noise(path, combo.noise_db, noise_dir) if combo.noise_db is not None else path
        name = os.path.basename(path)
        print(f"-- {name}")

        t0 = time.perf_counter()
        segments = transcriber(audio_path, combo.asr_model)
        asr_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        produced = diarize(segments, audio_path, combo.diarizer)
        diar_s = time.perf_counter() - t0

        result = score(number, produced)
        result.update({"file": name, "asr_seconds": round(asr_s, 1),
                       "diarization_seconds": round(diar_s, 1)})
        rows.append(result)
        print(f"   word {result['word_accuracy']:.1f}%   "
              f"speaker {result['speaker_accuracy']:.1f}%   "
              f"asr {asr_s:.0f}s   diarization {diar_s:.0f}s")

    n = len(rows)
    summary = {
        "combination": combo.number,
        "label": combo.label,
        "why": combo.why,
        "hyper_parameters": combo.hyper,
        "mean_word_accuracy": round(sum(r["word_accuracy"] for r in rows) / n, 1),
        "mean_speaker_accuracy": round(sum(r["speaker_accuracy"] for r in rows) / n, 1),
        "per_recording": rows,
    }

    print()
    print(f"mean word accuracy      {summary['mean_word_accuracy']}%"
          f"   {'meets' if summary['mean_word_accuracy'] >= TARGET else 'below'} the {TARGET}% target")
    print(f"mean speaker accuracy   {summary['mean_speaker_accuracy']}%")
    print("Per-recording figures are above; the mean alone hides the spread.")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"combination_{combo.number}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nwrote {out}")
    return summary
