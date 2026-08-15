"""
Measures how well doctor speech is classified into Objective / Assessment / Plan.

WHY THIS EXISTS
The Module 9.2 live run produced a SOAP note with an empty Assessment section
despite the doctor saying "This looks like migraine with aura", a greeting filed
under Plan, and the examination findings, diagnosis and treatment plan all piled
into Objective. This script turns that observation into a number so any fix can
be shown to work rather than asserted to.

METHOD
The reference scripts are fed to SOAPService.generate_draft directly, as if they
had been perfectly transcribed and perfectly diarized. ASR and diarization are
therefore removed from the measurement entirely — a misclassification here cannot
be blamed on a misheard word, and an improvement here cannot be an artefact of a
better transcript. This measures the classifier and nothing else.

Ground truth is docs/evidence/soap_expected.md: every doctor sentence labelled
O, A, P, or X (belongs in no section). It was labelled from the scripts, not from
any system output.

TWO NUMBERS ARE REPORTED, and both matter.

  Clinical accuracy — of the sentences that belong in the note, how many reached
  the right section. A note that files the diagnosis under Objective is wrong
  even though every word is present.

  Noise rate — how much of what belongs in no section leaked in anyway.
  Questions the doctor asked, and greetings. A note can score well on accuracy
  while being unusable because it is padded with "Good morning" and "Can you
  describe the pain for me?".

Usage:
    python -m scripts.evaluate_soap              # the four reference scripts
    python -m scripts.evaluate_soap --heldout    # unseen clinical scenarios
"""

import os
import re
import sys
from typing import Dict, List, Tuple

EVIDENCE_DIR = os.path.join("docs", "evidence")
SCRIPTS_MD = os.path.join(EVIDENCE_DIR, "consultation_scripts.md")
EXPECTED_MD = os.path.join(EVIDENCE_DIR, "soap_expected.md")
HELDOUT_MD = os.path.join(EVIDENCE_DIR, "soap_heldout.md")

SECTION_OF_LABEL = {"O": "objective", "A": "assessment", "P": "plan"}
WORD_RE = re.compile(r"[a-z0-9']+")


def words(text: str) -> List[str]:
    return WORD_RE.findall(text.lower())


def contains(haystack: List[str], needle: List[str]) -> bool:
    """True if needle appears as a contiguous run inside haystack."""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i] == first and haystack[i:i + len(needle)] == needle:
            return True
    return False


def parse_scripts(path: str) -> Dict[int, List[Dict[str, str]]]:
    """{script_number: [{"speaker_role": ..., "text": ...}, ...]}"""
    if not os.path.exists(path):
        sys.exit(f"FATAL: {path} not found.")
    out: Dict[int, List[Dict[str, str]]] = {}
    current = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^##\s*Script\s+(\d+)", line)
        if m:
            current = int(m.group(1))
            out[current] = []
            continue
        if current is None:
            continue
        m = re.match(r"^(DOCTOR|PATIENT):\s*(.+?)\s*$", line)
        if m:
            out[current].append({"speaker_role": m.group(1), "text": m.group(2)})
    return {k: v for k, v in out.items() if v}


def parse_expected(path: str) -> Dict[int, List[Tuple[str, str]]]:
    """{script_number: [(label, sentence), ...]}"""
    if not os.path.exists(path):
        sys.exit(f"FATAL: {path} not found.")
    out: Dict[int, List[Tuple[str, str]]] = {}
    current = None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^##\s*Script\s+(\d+)", line)
        if m:
            current = int(m.group(1))
            out[current] = []
            continue
        if current is None:
            continue
        m = re.match(r"^([OAPX])\s*\|\s*(.+?)\s*$", line)
        if m:
            out[current].append((m.group(1), m.group(2)))
    return {k: v for k, v in out.items() if v}


def main() -> None:
    from app.services.soap_service import SOAPService

    heldout = "--heldout" in sys.argv[1:]

    if heldout:
        # The held-out file contains only labelled doctor sentences, so each one
        # becomes its own segment. That isolates classification: sentence
        # splitting is already exercised by the reference scripts, and what is
        # under test here is whether the speech-act cues generalise beyond the
        # consultations they were written against.
        expected = parse_expected(HELDOUT_MD)
        scripts = {
            n: [{"speaker_role": "DOCTOR", "text": sentence}
                for _, sentence in sentences]
            for n, sentences in expected.items()
        }
        print("HELD-OUT SET — clinical scenarios absent from the reference "
              "scripts.\nIf this scores far below the reference set, the "
              "speech-act cues are fitted\nto the reference scripts and that "
              "score cannot be trusted.\n")
    else:
        scripts = parse_scripts(SCRIPTS_MD)
        expected = parse_expected(EXPECTED_MD)

    if not scripts or not expected:
        sys.exit("FATAL: nothing parsed.")

    print(f"Consultations: {len(scripts)}   labelled sentences: "
          f"{sum(len(v) for v in expected.values())}\n")

    clinical_right = clinical_total = 0
    noise_leaked = noise_total = 0
    per_label = {"O": [0, 0], "A": [0, 0], "P": [0, 0]}
    misplaced: List[str] = []
    leaked: List[str] = []

    for n in sorted(scripts):
        if n not in expected:
            continue

        print(f"--- Script {n} ---", flush=True)
        draft = SOAPService.generate_draft(scripts[n])
        section_words = {k: words(v) for k, v in draft.items()}

        s_right = s_total = s_leak = s_noise = 0

        for label, sentence in expected[n]:
            needle = words(sentence)
            found_in = [
                sec for sec in ("objective", "assessment", "plan", "subjective")
                if contains(section_words.get(sec, []), needle)
            ]

            if label == "X":
                noise_total += 1
                s_noise += 1
                if found_in:
                    noise_leaked += 1
                    s_leak += 1
                    leaked.append(f"    [{n}] {found_in[0]:<10} <- {sentence[:64]}")
                continue

            want = SECTION_OF_LABEL[label]
            clinical_total += 1
            s_total += 1
            per_label[label][1] += 1

            if want in found_in:
                clinical_right += 1
                s_right += 1
                per_label[label][0] += 1
            else:
                where = found_in[0] if found_in else "DROPPED"
                misplaced.append(
                    f"    [{n}] want {want:<10} got {where:<10} <- {sentence[:56]}"
                )

        acc = (s_right / s_total * 100) if s_total else 0.0
        leak = (s_leak / s_noise * 100) if s_noise else 0.0
        print(f"  clinical accuracy   {s_right}/{s_total}  ({acc:.1f}%)")
        print(f"  noise leaked in     {s_leak}/{s_noise}  ({leak:.1f}%)")
        print()

    print("=" * 66)
    print("SUMMARY")
    print("=" * 66)
    acc = (clinical_right / clinical_total * 100) if clinical_total else 0.0
    leak = (noise_leaked / noise_total * 100) if noise_total else 0.0
    print(f"  Clinical accuracy   {clinical_right}/{clinical_total}  ({acc:.1f}%)"
          "   <- of what belongs in the note, how much reached the right section")
    print(f"  Noise rate          {noise_leaked}/{noise_total}  ({leak:.1f}%)"
          "   <- of what belongs nowhere, how much got in anyway")
    print()
    print("  By section:")
    for label, name in (("O", "Objective"), ("A", "Assessment"), ("P", "Plan")):
        right, total = per_label[label]
        pct = (right / total * 100) if total else 0.0
        print(f"    {name:<12} {right:>2}/{total:<3} ({pct:5.1f}%)")

    if misplaced:
        print(f"\n  Misplaced ({len(misplaced)}):")
        for line in misplaced[:20]:
            print(line)
        if len(misplaced) > 20:
            print(f"    ... and {len(misplaced) - 20} more")

    if leaked:
        print(f"\n  Leaked in that should not be there ({len(leaked)}):")
        for line in leaked[:20]:
            print(line)
        if len(leaked) > 20:
            print(f"    ... and {len(leaked) - 20} more")

    print("\nBoth numbers matter. High accuracy with a high noise rate is a note")
    print("padded with greetings and questions; low noise with low accuracy is a")
    print("tidy note with the diagnosis filed in the wrong place.")


if __name__ == "__main__":
    main()
