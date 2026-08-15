"""
Module 9.1 Part B — Accuracy evaluation against the SRS 2.3.3 targets.

Measures two requirements that have never been measured:

  1. ASR word accuracy            SRS target: >= 85%
  2. Speaker (diarization) accuracy   SRS target: >= 85%

METHOD
Reference text is read directly from docs/evidence/consultation_scripts.md,
so the ground truth is whatever was scripted. Each "## Script N" section maps
to docs/evidence/consult_N.wav.

The pipeline is invoked directly (ASRService -> DiarizationService), not over
HTTP. No server, no database, no background tasks — this measures the models,
not the plumbing.

  Word accuracy: word error rate between the reference and the hypothesis,
  computed by Levenshtein distance over word sequences. Reported twice —
  once over all words, and once with numeric tokens removed, because the
  scripts spell numbers out ("one forty over ninety") while Whisper often
  writes digits ("140/90"). That is a formatting difference, not a
  recognition error, and inflating WER with it would be misleading.

  Speaker accuracy: reference and hypothesis word sequences are aligned with
  difflib. For every word the aligner matches in both, the predicted speaker
  is compared with the true speaker. Accuracy is correct matches over total
  matches. Words that were misheard are excluded, so this measures speaker
  labelling rather than re-measuring ASR.

HONESTY NOTE
Do not tune the diarization threshold against these recordings and re-run.
That converts a measurement into a fitting exercise and makes the number
meaningless. Report whatever it says.

AUDIO SETS
By default the human recordings in docs/evidence are evaluated. A second set
can be measured with --audio-dir, which is how the synthetic control condition
is run:

    python -m scripts.evaluate_accuracy
    python -m scripts.evaluate_accuracy --audio-dir docs/evidence/synthetic

The reference text always comes from docs/evidence/consultation_scripts.md, so
both sets are scored against identical ground truth and the two results are
directly comparable. Each set writes its labelled transcripts beside its own
audio, so neither run overwrites the other's evidence.

Usage:
    python -m scripts.evaluate_accuracy [--audio-dir PATH]
"""

import difflib
import os
import re
import sys
import wave
from typing import Dict, List, Tuple

EVIDENCE_DIR = os.path.join("docs", "evidence")
SCRIPTS_MD = os.path.join(EVIDENCE_DIR, "consultation_scripts.md")
TARGET = 85.0

WORD_RE = re.compile(r"[a-z0-9']+")
NUMERIC_RE = re.compile(r"^[0-9]+$")


# --------------------------------------------------------------------------
# Reference parsing
# --------------------------------------------------------------------------

def parse_scripts(path: str) -> Dict[int, List[Tuple[str, str]]]:
    """Return {script_number: [(speaker, text), ...]} from the markdown file."""
    if not os.path.exists(path):
        sys.exit(f"FATAL: {path} not found.")

    scripts: Dict[int, List[Tuple[str, str]]] = {}
    current = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^##\s*Script\s+(\d+)", line)
        if m:
            current = int(m.group(1))
            scripts[current] = []
            continue
        if current is None:
            continue
        m = re.match(r"^(DOCTOR|PATIENT):\s*(.+?)\s*$", line)
        if m:
            scripts[current].append((m.group(1), m.group(2)))
    return {k: v for k, v in scripts.items() if v}


def normalise(text: str) -> List[str]:
    return WORD_RE.findall(text.lower())


def strip_numerics(words: List[str]) -> List[str]:
    return [w for w in words if not NUMERIC_RE.match(w)]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def word_error_rate(ref: List[str], hyp: List[str]) -> float:
    """Levenshtein distance over word sequences, divided by reference length."""
    if not ref:
        return 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(
                prev[j] + 1,          # deletion
                cur[j - 1] + 1,       # insertion
                prev[j - 1] + (r != h)  # substitution
            )
        prev = cur
    return prev[-1] / len(ref)


def speaker_accuracy(ref_words: List[str], ref_spk: List[str],
                     hyp_words: List[str], hyp_spk: List[str]) -> Tuple[int, int]:
    """Align word sequences; compare speaker labels on matched words."""
    sm = difflib.SequenceMatcher(a=ref_words, b=hyp_words, autojunk=False)
    correct = total = 0
    for a0, b0, size in sm.get_matching_blocks():
        for k in range(size):
            total += 1
            if ref_spk[a0 + k] == hyp_spk[b0 + k]:
                correct += 1
    return correct, total


def audio_duration(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_audio_dir(argv: List[str]) -> str:
    """--audio-dir PATH, defaulting to the human recordings."""
    if "--audio-dir" in argv:
        i = argv.index("--audio-dir")
        if i + 1 >= len(argv):
            sys.exit("FATAL: --audio-dir needs a path.")
        path = argv[i + 1]
        if not os.path.isdir(path):
            sys.exit(f"FATAL: {path} is not a directory.")
        return path
    return EVIDENCE_DIR


def main() -> None:
    from app.services.asr_service import ASRService
    from app.services.diarization_service import DiarizationService

    audio_dir = parse_audio_dir(sys.argv[1:])
    print(f"Audio set: {audio_dir}")
    if "synthetic" in os.path.basename(os.path.abspath(audio_dir)).lower():
        print("NOTE: synthetic audio. No overlapping speech, background noise or\n"
              "      disfluency, so these scores are a control condition and must\n"
              "      not be reported as real-world performance.")
        print()
    elif os.path.abspath(audio_dir) != os.path.abspath(EVIDENCE_DIR):
        print(f"NOTE: alternative recording set ({os.path.basename(audio_dir)}).\n"
              "      Report which set a figure came from; the sets differ in\n"
              "      recording conditions, not in the words spoken.")
        print()

    scripts = parse_scripts(SCRIPTS_MD)
    if not scripts:
        sys.exit("FATAL: no scripts parsed from the markdown file.")

    print(f"Parsed {len(scripts)} reference script(s) from {SCRIPTS_MD}\n")

    rows = []
    transcript_dump = []

    for n in sorted(scripts):
        wav = os.path.join(audio_dir, f"consult_{n}.wav")
        if not os.path.exists(wav):
            print(f"Script {n}: SKIPPED — {wav} not found")
            continue

        turns = scripts[n]
        ref_words: List[str] = []
        ref_spk: List[str] = []
        for speaker, text in turns:
            words = normalise(text)
            ref_words.extend(words)
            ref_spk.extend([speaker] * len(words))

        print(f"--- Script {n} ({audio_duration(wav):.1f}s, "
              f"{len(turns)} reference turns, {len(ref_words)} words) ---")
        print("  running ASR ...", flush=True)

        asr = ASRService.transcribe_audio(wav)
        diarized = DiarizationService.diarize_segments(asr.get("segments", []), wav)

        hyp_words: List[str] = []
        hyp_spk: List[str] = []
        for seg in diarized:
            words = normalise(seg["text"])
            hyp_words.extend(words)
            hyp_spk.extend([seg["speaker_role"]] * len(words))

        wer_all = word_error_rate(ref_words, hyp_words)
        wer_nonum = word_error_rate(strip_numerics(ref_words),
                                    strip_numerics(hyp_words))
        wacc_all = max(0.0, 1 - wer_all) * 100
        wacc_nonum = max(0.0, 1 - wer_nonum) * 100

        correct, total = speaker_accuracy(ref_words, ref_spk, hyp_words, hyp_spk)
        spk_acc = (correct / total * 100) if total else 0.0

        print(f"  segments produced      {len(diarized)}")
        print(f"  word accuracy          {wacc_all:.1f}%  "
              f"(excluding numerals: {wacc_nonum:.1f}%)")
        print(f"  speaker accuracy       {spk_acc:.1f}%  "
              f"({correct}/{total} aligned words)")
        print()

        rows.append((n, wacc_all, wacc_nonum, spk_acc, len(diarized), len(turns)))

        transcript_dump.append(f"===== Script {n} =====")
        for seg in diarized:
            transcript_dump.append(f"{seg['speaker_role']}: {seg['text']}")
        transcript_dump.append("")

    if not rows:
        sys.exit("No recordings evaluated. Convert your audio into "
                 f"{audio_dir}\\consult_1.wav etc. and try again.")

    mean_wacc = sum(r[1] for r in rows) / len(rows)
    mean_wacc_nonum = sum(r[2] for r in rows) / len(rows)
    mean_spk = sum(r[3] for r in rows) / len(rows)

    print("=" * 62)
    print("SUMMARY")
    print("=" * 62)
    print(f"{'Script':<8}{'WordAcc':>10}{'WA(no num)':>13}{'SpeakerAcc':>13}"
          f"{'Segs':>7}{'Turns':>7}")
    for n, w, wn, s, segs, turns in rows:
        print(f"{n:<8}{w:>9.1f}%{wn:>12.1f}%{s:>12.1f}%{segs:>7}{turns:>7}")
    print("-" * 62)
    print(f"{'MEAN':<8}{mean_wacc:>9.1f}%{mean_wacc_nonum:>12.1f}%"
          f"{mean_spk:>12.1f}%")
    print()
    print(f"SRS 2.3.3 ASR word accuracy      target >= {TARGET}%  ->  "
          f"{'MET' if mean_wacc_nonum >= TARGET else 'NOT MET'}"
          f"  (using the numeral-excluded figure)")
    print(f"SRS 2.3.3 Diarization accuracy   target >= {TARGET}%  ->  "
          f"{'MET' if mean_spk >= TARGET else 'NOT MET'}")
    print()
    print("Note: 'Segs' vs 'Turns' is worth reading. Segs is how many speaker")
    print("turns the system found; Turns is how many are really there. Segs far")
    print("below Turns means the two voices were merged rather than separated,")
    print("and when that happens the accuracy figure mostly reflects which")
    print("cluster happened to be named DOCTOR, not how well anything worked.")

    out = os.path.join(audio_dir, "diarized_output.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(transcript_dump))
    print(f"\nDiarized transcripts written to {out} — read them. The numbers")
    print("tell you how well it did; the transcript tells you how it failed.")


if __name__ == "__main__":
    main()
