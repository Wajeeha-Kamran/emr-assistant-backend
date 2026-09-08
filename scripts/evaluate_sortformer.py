"""
Sortformer vs pyannote on this machine's CPU.

WHY THIS EXISTS
The 99.9% speaker accuracy for Sortformer was measured on a Colab T4, in a
separate notebook, because NeMo and pyannote could not be installed together at
the time. Both of those constraints are gone: NeMo 3.0.0, openai-whisper and
pyannote.audio 4.0.7 install and import in one Python 3.12 environment on
Windows. So the comparison can now be run here, on the hardware the system
actually deploys to, in a single process.

WHAT IT DOES NOT CHANGE
The scoring functions are imported from scripts/evaluate_accuracy.py — the same
code behind every accuracy figure in the report. The doctor-identification rule
(whoever asks more questions) is held constant across both diarizers, exactly as
it was in notebook 05, so what is compared is the diarizer and nothing else.

USAGE
    python -m scripts.evaluate_sortformer
    python -m scripts.evaluate_sortformer --audio-dir docs/evidence/human_distinct
    python -m scripts.evaluate_sortformer --skip-pyannote

pyannote needs HF_TOKEN in the environment; it is skipped automatically if unset.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.getcwd())

from scripts.evaluate_accuracy import (          # noqa: E402
    EVIDENCE_DIR, SCRIPTS_MD, parse_scripts, normalise, strip_numerics,
    word_error_rate, speaker_accuracy, audio_duration,
)

DEFAULT_AUDIO_DIR = os.path.join(EVIDENCE_DIR, "human_distinct")
OUT_CSV = os.path.join(EVIDENCE_DIR, "benchmarks", "sortformer_cpu_detail.csv")
SORTFORMER_ID = "nvidia/diar_sortformer_4spk-v1"


# --------------------------------------------------------------- timing
class Measured:
    """Wall clock and process CPU time for one stage."""

    def __enter__(self):
        self.w0, self.c0 = time.perf_counter(), time.process_time()
        return self

    def __exit__(self, *exc):
        self.wall = round(time.perf_counter() - self.w0, 2)
        self.cpu = round(time.process_time() - self.c0, 2)
        return False


# ------------------------------------------- shared with notebook 05
def assign_roles(segments):
    """Label the more question-asking cluster DOCTOR. Mirrors DiarizationService."""
    counts: Dict[Any, int] = {}
    for s in segments:
        counts[s["speaker"]] = counts.get(s["speaker"], 0) + s["text"].count("?")
    if not counts:
        return segments
    doctor = max(counts, key=counts.get)
    for s in segments:
        s["speaker_role"] = "DOCTOR" if s["speaker"] == doctor else "PATIENT"
    return segments


def as_annotation(result):
    """Accept either a pyannote.core.Annotation (3.x) or a DiarizeOutput (4.x).

    Same normalisation as PyannoteEngine._as_annotation in app/ml/pyannote_engine.py.
    exclusive_speaker_diarization is preferred because overlapping speech is
    removed, which is what word-level attribution needs.
    """
    if hasattr(result, "itertracks"):
        return result
    for attr in ("exclusive_speaker_diarization", "speaker_diarization"):
        candidate = getattr(result, attr, None)
        if candidate is not None and hasattr(candidate, "itertracks"):
            return candidate
    raise TypeError(
        f"pyannote returned {type(result).__name__} with no usable "
        f"diarization attribute")


def words_to_turns(words, spans):
    def speaker_at(t):
        for start, end, spk in spans:
            if start <= t <= end:
                return spk
        return (min(spans, key=lambda s: min(abs(s[0] - t), abs(s[1] - t)))[2]
                if spans else "A")

    merged, current = [], None
    for w in words:
        spk = speaker_at((w["start"] + w["end"]) / 2)
        if current is None or current["speaker"] != spk:
            if current:
                merged.append(current)
            current = {"speaker": spk, "text": w["word"]}
        else:
            current["text"] += w["word"]
    if current:
        merged.append(current)
    return assign_roles(merged)


def score(scripts, n, segments) -> Tuple[float, float]:
    ref_words, ref_spk = [], []
    for speaker, text in scripts[n]:
        w = normalise(text)
        ref_words.extend(w)
        ref_spk.extend([speaker] * len(w))
    hyp_words, hyp_spk = [], []
    for seg in segments:
        w = normalise(seg["text"])
        hyp_words.extend(w)
        hyp_spk.extend([seg["speaker_role"]] * len(w))
    wacc = max(0.0, 1 - word_error_rate(
        strip_numerics(ref_words), strip_numerics(hyp_words))) * 100
    correct, total = speaker_accuracy(ref_words, ref_spk, hyp_words, hyp_spk)
    return wacc, (correct / total * 100) if total else 0.0


# ------------------------------------------------------------ audio prep
_SF: Dict[str, str] = {}


def mono16k(wav: str) -> str:
    """Sortformer expects mono 16 kHz. Converted copies go in a temp folder."""
    if wav in _SF:
        return _SF[wav]
    import soundfile as sf
    audio, sr = sf.read(wav)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        import librosa
        audio = librosa.resample(audio.astype("float32"), orig_sr=sr, target_sr=16000)
    out_dir = os.path.join(EVIDENCE_DIR, "benchmarks", "_sf16k")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(wav))
    sf.write(out, audio, 16000, subtype="PCM_16")
    _SF[wav] = out
    return out


def spans_from_sortformer(pred) -> List[Tuple[float, float, str]]:
    raw = pred[0] if isinstance(pred, (list, tuple)) and pred else pred
    spans = []
    for s in raw:
        if isinstance(s, str):
            p = s.replace(",", " ").split()
            spans.append((float(p[0]), float(p[1]), str(p[2])))
        elif isinstance(s, (list, tuple)) and len(s) >= 3:
            spans.append((float(s[0]), float(s[1]), str(s[2])))
        else:
            raise RuntimeError(f"unexpected Sortformer segment: {type(s)} {s!r}")
    return spans


# ------------------------------------------------------------------ main
def main() -> None:
    audio_dir = DEFAULT_AUDIO_DIR
    skip_pyannote = "--skip-pyannote" in sys.argv
    if "--audio-dir" in sys.argv:
        audio_dir = sys.argv[sys.argv.index("--audio-dir") + 1]

    scripts = parse_scripts(SCRIPTS_MD)
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}   audio: {audio_dir}")

    # ---- Whisper, once per clip; both diarizers score the same words ----
    import whisper
    with Measured() as m_load:
        asr = whisper.load_model("base.en", device=device)
    print(f"whisper base.en loaded in {m_load.wall}s")

    words: Dict[int, List[dict]] = {}
    asr_time: Dict[int, Tuple[float, float]] = {}
    durations: Dict[int, float] = {}
    for n in sorted(scripts):
        wav = os.path.join(audio_dir, f"consult_{n}.wav")
        durations[n] = audio_duration(wav)
        with Measured() as m:
            r = asr.transcribe(wav, language="en", word_timestamps=True)
        ws = [w for seg in r.get("segments", []) for w in (seg.get("words") or [])]
        words[n] = ws
        asr_time[n] = (m.wall, m.cpu)
        print(f"  script {n}: {len(ws)} words, {m.wall}s "
              f"({m.wall / durations[n]:.2f}x realtime)")

    rows: List[dict] = []

    # ---------------------------------------------------------- Sortformer
    from nemo.collections.asr.models import SortformerEncLabelModel
    with Measured() as m_sf_load:
        sortformer = SortformerEncLabelModel.from_pretrained(SORTFORMER_ID)
        sortformer.eval()
        if device == "cuda":
            sortformer = sortformer.cuda()
    print(f"\nsortformer loaded in {m_sf_load.wall}s")

    for n in sorted(scripts):
        wav = os.path.join(audio_dir, f"consult_{n}.wav")
        with Measured() as m:
            pred = sortformer.diarize(audio=[mono16k(wav)], batch_size=1)
        segs = words_to_turns(words[n], spans_from_sortformer(pred))
        wacc, spk = score(scripts, n, segs)
        total = round(asr_time[n][0] + m.wall, 2)
        rows.append({
            "diarizer": "sortformer", "script": n,
            "word_acc": round(wacc, 1), "speaker_acc": round(spk, 1),
            "turns": len(segs), "ref_turns": len(scripts[n]),
            "audio_s": round(durations[n], 1),
            "asr_s": asr_time[n][0], "diar_s": m.wall, "total_s": total,
            "realtime_x": round(total / durations[n], 2),
            "cpu_s": round(asr_time[n][1] + m.cpu, 2), "device": device,
        })
        print(f"  script {n}: word {wacc:5.1f}%  speaker {spk:5.1f}%  "
              f"diar {m.wall}s")

    # ------------------------------------------------------------ pyannote
    if not skip_pyannote and os.environ.get("HF_TOKEN"):
        from pyannote.audio import Pipeline
        import soundfile as sf
        with Measured() as m_py_load:
            pipe = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=os.environ["HF_TOKEN"])
        print(f"\npyannote loaded in {m_py_load.wall}s")

        for n in sorted(scripts):
            wav = os.path.join(audio_dir, f"consult_{n}.wav")
            data, sr = sf.read(wav, dtype="float32", always_2d=True)
            wave = torch.from_numpy(data.T.copy())
            with Measured() as m:
                ann = pipe({"waveform": wave, "sample_rate": int(sr)},
                           num_speakers=2)
            spans = [(float(s.start), float(s.end), str(lbl))
                     for s, _, lbl in
                     as_annotation(ann).itertracks(yield_label=True)]
            segs = words_to_turns(words[n], spans)
            wacc, spk = score(scripts, n, segs)
            total = round(asr_time[n][0] + m.wall, 2)
            rows.append({
                "diarizer": "pyannote", "script": n,
                "word_acc": round(wacc, 1), "speaker_acc": round(spk, 1),
                "turns": len(segs), "ref_turns": len(scripts[n]),
                "audio_s": round(durations[n], 1),
                "asr_s": asr_time[n][0], "diar_s": m.wall, "total_s": total,
                "realtime_x": round(total / durations[n], 2),
                "cpu_s": round(asr_time[n][1] + m.cpu, 2), "device": device,
            })
            print(f"  script {n}: word {wacc:5.1f}%  speaker {spk:5.1f}%  "
                  f"diar {m.wall}s")
    elif not skip_pyannote:
        print("\npyannote skipped: HF_TOKEN is not set in the environment.")

    # -------------------------------------------------------------- output
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nwritten: {OUT_CSV}\n")
    print(f"{'diarizer':<12}{'word %':>9}{'speaker %':>11}{'x realtime':>12}")
    for d in ("sortformer", "pyannote"):
        rs = [r for r in rows if r["diarizer"] == d]
        if not rs:
            continue
        n = len(rs)
        print(f"{d:<12}"
              f"{sum(r['word_acc'] for r in rs) / n:>9.1f}"
              f"{sum(r['speaker_acc'] for r in rs) / n:>11.1f}"
              f"{sum(r['realtime_x'] for r in rs) / n:>12.2f}")
    print("\nPer-script figures are in the CSV. Do not quote a mean alone —")
    print("one collapsed recording hides behind three good ones.")


if __name__ == "__main__":
    main()
