"""
Score an export run against the Kaggle data set's own reference transcripts.

WHY THIS EXISTS
evaluate_accuracy.py scores against docs/evidence/consultation_scripts.md, the
scripts written for this project. That measures the system on audio it was
built alongside. The Kaggle set (najamahmed97/audio-recording-whisper) ships a
reference transcript for every recording with the speakers already labelled,
which allows the same two metrics to be computed on unscripted audio recorded
by other people. Those figures are the fairer estimate, and they are the ones
quoted in the report.

The metrics are copied from evaluate_accuracy.py rather than reimplemented, so
the two sets of numbers mean the same thing and can be compared directly.

Usage:
    python scripts/evaluate_kaggle.py
    python scripts/evaluate_kaggle.py kaggle_outputs.json "D:\\audio_recordings\\Clean_Transcripts"

Writes kaggle_scores.json beside the outputs file and prints a per-recording
table. Per-recording figures are printed above the means deliberately: a mean
on five recordings hides a spread of twelve points.
"""
import difflib
import json
import os
import re
import sys

WORD_RE = re.compile(r"[a-z0-9']+")
NUMERIC_RE = re.compile(r"^[0-9]+$")

DEFAULT_OUTPUTS = "kaggle_outputs.json"
DEFAULT_REF_DIR = r"D:\audio_recordings\Clean_Transcripts"


def normalise(text):
    return WORD_RE.findall(text.lower())


def strip_numerics(words):
    return [w for w in words if not NUMERIC_RE.match(w)]


def word_error_rate(ref, hyp):
    """Levenshtein distance over word sequences, divided by reference length."""
    if not ref:
        return 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(
                prev[j] + 1,             # deletion
                cur[j - 1] + 1,          # insertion
                prev[j - 1] + (r != h),  # substitution
            )
        prev = cur
    return prev[-1] / len(ref)


def speaker_accuracy(ref_words, ref_spk, hyp_words, hyp_spk):
    """Align the two word sequences; compare speaker labels where they match."""
    sm = difflib.SequenceMatcher(a=ref_words, b=hyp_words, autojunk=False)
    correct = total = 0
    for a0, b0, size in sm.get_matching_blocks():
        for k in range(size):
            total += 1
            if ref_spk[a0 + k] == hyp_spk[b0 + k]:
                correct += 1
    return correct, total


def parse_reference(path):
    """Read one Clean_Transcripts file into [(speaker, text), ...].

    The data set labels turns 'D:' and 'P:'. Two details matter and are easy to
    miss. Long turns wrap onto continuation lines that carry no speaker prefix,
    and CAR0001 uses 'D;' instead of 'D:'. A parser that accepts only prefixed
    lines silently drops those words from the reference; they then appear as
    insertions in the hypothesis and accuracy is understated - RES0001 lost
    eight lines that way, and its score moved from 74.0% to 81.7% once they
    were included. Continuation lines are appended to the turn above.
    """
    turns = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        m = re.match(r"^\s*([DP])[:;]\s*(.+?)\s*$", line)
        if m:
            turns.append(("DOCTOR" if m.group(1) == "D" else "PATIENT", m.group(2)))
        elif turns:
            speaker, text = turns[-1]
            turns[-1] = (speaker, text + " " + line.strip())
    return turns


def flatten(turns):
    """[(speaker, text), ...] -> (word list, speaker-per-word list)."""
    words, speakers = [], []
    for speaker, text in turns:
        for word in normalise(text):
            words.append(word)
            speakers.append(speaker)
    return words, speakers


def main():
    outputs = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUTS
    ref_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REF_DIR

    if not os.path.exists(outputs):
        sys.exit(f"FATAL: {outputs} not found. Run export_consultation_outputs.py first.")
    if not os.path.isdir(ref_dir):
        sys.exit(f"FATAL: {ref_dir} not found. Pass the Clean_Transcripts folder "
                 f"as the second argument.")

    rows = []
    for item in json.load(open(outputs, encoding="utf-8")):
        stem = os.path.splitext(item["audio_file"])[0]
        ref_path = os.path.join(ref_dir, stem + ".txt")
        if not os.path.exists(ref_path):
            print(f"SKIP {stem}: no reference transcript in {ref_dir}")
            continue

        ref_words, ref_spk = flatten(parse_reference(ref_path))
        hyp_words, hyp_spk = flatten(
            [(t["speaker"], t["text"]) for t in item["transcript"]])

        # Two word-accuracy figures, as evaluate_accuracy.py reports: the plain
        # one, and one with bare numerals removed. "39" against "thirty nine"
        # is a formatting difference, not a recognition error.
        wer = word_error_rate(ref_words, hyp_words)
        wer_nonum = word_error_rate(strip_numerics(ref_words), strip_numerics(hyp_words))
        correct, total = speaker_accuracy(ref_words, ref_spk, hyp_words, hyp_spk)

        rows.append({
            "file": item["audio_file"],
            "ref_words": len(ref_words),
            "hyp_words": len(hyp_words),
            "word_accuracy": round((1 - wer) * 100, 1),
            "word_accuracy_no_numerals": round((1 - wer_nonum) * 100, 1),
            "speaker_accuracy": round(correct / total * 100, 1) if total else None,
            "speaker_words_compared": total,
            "duration_s": round(item["transcript"][-1]["end"], 1) if item["transcript"] else 0.0,
        })

    if not rows:
        sys.exit("FATAL: nothing scored. No reference transcript matched any "
                 "audio_file name in the outputs file.")

    for r in rows:
        print(f"{r['file']:14s} ref={r['ref_words']:5d} hyp={r['hyp_words']:5d} "
              f"word={r['word_accuracy']:5.1f}%  "
              f"word_nonum={r['word_accuracy_no_numerals']:5.1f}%  "
              f"speaker={r['speaker_accuracy']:5.1f}% "
              f"({r['speaker_words_compared']} words compared)")

    n = len(rows)
    print(f"\nscored {n} recording(s)")
    print(f"mean word accuracy      {sum(r['word_accuracy'] for r in rows) / n:.1f}%")
    print(f"mean word (no numerals) {sum(r['word_accuracy_no_numerals'] for r in rows) / n:.1f}%")
    print(f"mean speaker accuracy   {sum(r['speaker_accuracy'] for r in rows) / n:.1f}%")

    out_path = os.path.join(os.path.dirname(os.path.abspath(outputs)), "kaggle_scores.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
