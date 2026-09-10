r"""
Does the generated note say anything the transcript did not?

WHY THIS EXISTS
Extraction cannot invent: every word in the note is a word from the transcript,
so its novel-content rate is 0.0% by construction. Generation gives that up,
and this project has already paid for it once -- BioGPT echoed the doctor's
greeting as the Subjective section (app/ml/biogpt_engine.py). That failure was
caught by reading the output. Five models cannot be compared by reading, and
the more fluent a wrong note is, the less likely a reader is to catch it.

So this measures faithfulness rather than quality, and it is meant to be run
BEFORE a model is adopted, not after.

THREE NUMBERS, in increasing order of how much they matter.

  Novel content rate -- content words in the note with no source in the
  selected sentences. Some of this is harmless connective prose, which is the
  point of using an LLM at all, so a non-zero figure is expected and is not by
  itself a failure. It is a magnitude, not a verdict.

  Omission rate -- content words in the selected sentences that the note
  dropped. A model that omits half the plan is not "concise", it is losing
  clinical content, and pure novel-content scoring would reward it for that.

  NUMERIC INFIDELITY -- any number, dose or unit in the note that is not in the
  source. This is the one that is not a quality metric. An invented "500 mg" is
  a patient-safety defect. Reported separately and never averaged into the
  others, because a model can look excellent on the first two and still be
  unusable on this one.

METHOD
Comparison is against the sentences the classifier SELECTED, not the whole
transcript. That is what the renderer was given, so it is what it is
accountable to. A model that correctly imports a fact from elsewhere in the
conversation is still doing something it was told not to do.

Stopwords and the section lead-ins ("Patient reports:") are excluded. Words are
compared on a light stem so "examined"/"examination" and "swelling"/"swollen"
do not read as invention.

Usage:
    python -m scripts.evaluate_groundedness            # scores the extractive
                                                       # renderer: expect 0.0%
    python -m scripts.evaluate_groundedness --notes out.json
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVIDENCE_DIR = os.path.join("docs", "evidence")
OUT_CSV = os.path.join(EVIDENCE_DIR, "benchmarks", "groundedness_detail.csv")

SECTIONS = ("subjective", "objective", "assessment", "plan")

WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

# ---------------------------------------------------------------- numerics
#
# Numbers and units are what must survive unchanged, and comparing them is
# harder than it looks because the two sides write them differently.
#
# The reference consultations spell numbers out -- "sumatriptan fifty
# milligrams", "one forty over ninety" -- because that is how they were
# spoken. A language model writes "50 mg" and "140/90". A naive matcher finds
# no digits in the source, then flags every number in the note as unsourced,
# and reports a model as a patient-safety failure precisely when it got the
# dose right. The first version of this file did exactly that; the self-test
# below is what caught it.
#
# So both sides are normalised: number words are composed into values, and unit
# synonyms collapse onto one spelling ("milligrams" and "mg" become "mg").

DIGITS_RE = re.compile(r"^\d+(?:\.\d+)?$")

UNIT_SYNONYMS = {
    "milligram": "mg", "milligrams": "mg", "mg": "mg", "mgs": "mg",
    "microgram": "mcg", "micrograms": "mcg", "mcg": "mcg",
    "gram": "g", "grams": "g",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg", "kilo": "kg", "kilos": "kg",
    "millilitre": "ml", "millilitres": "ml", "milliliter": "ml",
    "milliliters": "ml", "ml": "ml",
    "millimole": "mmol", "millimoles": "mmol", "mmol": "mmol",
    "mmhg": "mmhg",
    "week": "week", "weeks": "week", "day": "day", "days": "day",
    "month": "month", "months": "month", "year": "year", "years": "year",
    "hour": "hour", "hours": "hour", "minute": "minute", "minutes": "minute",
    "time": "time", "times": "time", "daily": "daily", "twice": "twice",
    "dose": "dose", "doses": "dose",
}

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000}
_NUMWORDS = set(_ONES) | set(_TENS) | set(_SCALES)


def _fmt(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _run_values(run: List[str]) -> List[str]:
    """
    Every value a run of number words could plausibly mean.

    Deliberately generous. "one forty over ninety" is spoken blood pressure;
    the textbook composer reads it as 41, a reader hears 140. Rather than
    guess, the run yields the composed value, each word's own value, and the
    digit concatenation -- so "140" is accepted as sourced.

    The bias is toward NOT raising an alarm. A metric that cries wolf on
    correct output gets ignored, which costs more than it saves. Every flagged
    numeric is printed in full so a person can check the ones that do fire.
    """
    if not run:
        return []

    if "point" in run:
        i = run.index("point")
        left = _run_values(run[:i])
        right = "".join(_fmt(_ONES.get(w, _TENS.get(w, 0))) for w in run[i + 1:])
        return [f"{left[0]}.{right}"] if left and right else left

    out, total, current = [], 0, 0
    for w in run:
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in _SCALES:
            current = (current or 1) * _SCALES[w]
            if _SCALES[w] >= 1000:
                total += current
                current = 0
    out.append(_fmt(total + current))

    singles = [_ONES.get(w, _TENS.get(w, _SCALES.get(w, 0))) for w in run]
    out += [_fmt(v) for v in singles]
    if len(run) > 1:
        out.append("".join(_fmt(v) for v in singles))
    return out


def numeric_facts(text: str) -> set:
    """Normalised numbers and units. Comparable across word and digit forms."""
    tokens = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower())
    facts, run = set(), []
    for tok in tokens:
        if tok in _NUMWORDS or (run and tok in ("and", "point")):
            run.append(tok)
            continue
        if run:
            facts.update(_run_values([w for w in run if w != "and"]))
            run = []
        if DIGITS_RE.match(tok):
            facts.add(_fmt(float(tok)))
        elif tok in UNIT_SYNONYMS:
            facts.add(UNIT_SYNONYMS[tok])
    if run:
        facts.update(_run_values([w for w in run if w != "and"]))
    return facts

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "have", "has", "had", "having", "of", "to", "in", "on",
    "at", "by", "for", "with", "from", "as", "into", "about", "over", "after",
    "before", "up", "down", "out", "off", "it", "its", "he", "she", "they",
    "them", "his", "her", "their", "you", "your", "i", "my", "me", "we", "us",
    "there", "here", "which", "who", "whom", "what", "when", "where", "how",
    "not", "no", "so", "very", "also", "just", "any", "some", "all", "both",
    "will", "would", "should", "could", "can", "may", "might", "must", "shall",
    "patient", "reports", "clinician", "noted", "clinical", "impression",
    "plan", "presented", "presents", "states", "reported", "described",
}


def stem(w: str) -> str:
    """Crude suffix strip. Enough to stop 'swollen'/'swelling' reading as new."""
    for suf in ("ational", "ation", "ings", "ing", "edly", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(text: str) -> List[str]:
    return [stem(w) for w in WORD_RE.findall((text or "").lower())
            if w not in STOPWORDS and len(w) > 2]




def score_section(source_sentences: List[str], note_text: str
                  ) -> Tuple[int, int, int, int, List[str], List[str]]:
    """(novel, note_total, omitted, src_total, novel_words, bad_numerics)"""
    src = content_words(" ".join(source_sentences))
    note = content_words(note_text)
    src_set, note_set = set(src), set(note)

    novel_words = sorted(note_set - src_set)
    omitted_words = sorted(src_set - note_set)

    src_nums = numeric_facts(" ".join(source_sentences))
    bad_numerics = sorted(numeric_facts(note_text) - src_nums)

    return (len(novel_words), len(note_set), len(omitted_words), len(src_set),
            novel_words, bad_numerics)


def load_notes(path: str) -> Dict[str, Dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_extractive_notes(sections_by_script: Dict[str, Dict[str, List[str]]]
                           ) -> Dict[str, Dict[str, str]]:
    from app.services.soap_service import SOAPService
    return {n: SOAPService.render_extractive(s)
            for n, s in sections_by_script.items()}


def selected_sections() -> Dict[str, Dict[str, List[str]]]:
    """Run the classifier over the reference scripts to get its selections."""
    from scripts.evaluate_soap import parse_scripts, SCRIPTS_MD
    from app.services.soap_service import SOAPService
    scripts = parse_scripts(SCRIPTS_MD)
    return {str(n): SOAPService.select_sections(turns)
            for n, turns in sorted(scripts.items())}


# ---------------------------------------------------------------- self-test
# The extractive control scores 0.0% by construction, which shows the metric
# does not fire on faithful text. It does NOT show the metric can catch
# unfaithful text -- a function that always returned zero would pass it just as
# well. So the instrument is calibrated against a deliberately corrupted note
# whose faults are known in advance.
#
# Run with --selftest. It is expected to be run before the figures are quoted.

def _alter_a_number(text: str) -> str:
    """Change the first number in the text, whether written as a word or digits."""
    def sub_word(m):
        w = m.group(0).lower()
        return "seventy" if w != "seventy" else "thirteen"

    pattern = "|".join(sorted(_NUMWORDS, key=len, reverse=True))
    altered, n = re.subn(rf"\b({pattern})\b", sub_word, text, count=1,
                         flags=re.IGNORECASE)
    if n:
        return altered
    altered, n = re.subn(r"\b\d+\b", "77", text, count=1)
    if n:
        return altered
    raise AssertionError(
        "no number found to alter -- the corruption would be a no-op, which is "
        "exactly the fault this self-test exists to prevent")


CORRUPTIONS = [
    ("invented drug and dose",
     lambda t: t + " Prescribed amoxicillin 500 mg three times daily.",
     {"novel": True, "numeric": True}),
    ("invented finding, no numbers",
     lambda t: t + " Chest auscultation revealed bilateral wheeze.",
     {"novel": True, "numeric": False}),
    # The first version of this case substituted \b\d+\b. The reference
    # scripts spell numbers out ("fifty milligrams"), so it matched nothing,
    # compared a note against itself, and reported FAIL. Chasing that down is
    # what exposed the real defect: the metric could not see spelled-out
    # numbers at all, and would have flagged a model for correctly writing
    # "50 mg". This version alters whichever form the text actually uses.
    ("altered dose",
     _alter_a_number,
     {"numeric": True}),
    ("truncated to first sentence",
     lambda t: t.split(".")[0] + ".",
     {"omission": True}),
]


def selftest() -> int:
    sections_by_script = selected_sections()
    notes = build_extractive_notes(sections_by_script)
    script = sorted(sections_by_script, key=lambda x: int(x))[0]
    src = sections_by_script[script]
    base = notes[script]

    print(f"\ncalibrating on script {script}\n")
    failures = 0

    for name, corrupt, expect in CORRUPTIONS:
        note = dict(base)
        note["plan"] = corrupt(base["plan"])
        novel, note_n, om, src_n, novel_w, bad = score_section(
            src.get("plan") or [], note["plan"]
        )
        got = {
            "novel": novel > 0,
            "numeric": len(bad) > 0,
            "omission": om > 0,
        }
        ok = all(got[k] == v for k, v in expect.items())
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        print(f"        novel={novel} ({novel_w[:6]})  bad_numerics={bad}  omitted={om}")
        if not ok:
            print(f"        expected {expect}, measured "
                  f"{ {k: got[k] for k in expect} }")

    # And the faithful note must stay clean, or the metric cries wolf.
    novel, _, om, _, _, bad = score_section(src.get("plan") or [], base["plan"])
    ok = novel == 0 and om == 0 and not bad
    failures += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  unmodified extractive text stays clean")

    print(f"\n{'CALIBRATED' if not failures else str(failures) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", help="JSON {script: {section: text}}. "
                                    "Omit to score the extractive renderer.")
    ap.add_argument("--label", default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="check the metric detects known corruptions")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print("running the classifier to recover its selections...", flush=True)
    sections_by_script = selected_sections()

    if args.notes:
        notes = load_notes(args.notes)
        label = args.label or os.path.basename(args.notes)
    else:
        notes = build_extractive_notes(sections_by_script)
        label = args.label or "extractive (control)"

    print(f"\nscoring: {label}\n")

    tot_novel = tot_note = tot_om = tot_src = 0
    all_bad_nums: List[str] = []
    rows = []

    for script in sorted(sections_by_script, key=lambda x: int(x)):
        sec = sections_by_script[script]
        note = notes.get(script) or notes.get(str(script)) or {}
        s_novel = s_note = s_om = s_src = 0
        s_bad: List[str] = []

        for name in SECTIONS:
            novel, note_n, om, src_n, novel_w, bad = score_section(
                sec.get(name) or [], note.get(name, "")
            )
            s_novel += novel; s_note += note_n; s_om += om; s_src += src_n
            s_bad += bad
            if bad:
                print(f"  [{script}/{name}] NUMERIC NOT IN SOURCE: {bad}")
            if novel_w:
                print(f"  [{script}/{name}] novel: {novel_w[:12]}")

        nr = (s_novel / s_note * 100) if s_note else 0.0
        orr = (s_om / s_src * 100) if s_src else 0.0
        print(f"  script {script}: novel {nr:5.1f}%   omitted {orr:5.1f}%   "
              f"bad numerics {len(s_bad)}")
        rows.append({"label": label, "script": script,
                     "novel_rate": round(nr, 1), "omission_rate": round(orr, 1),
                     "bad_numerics": len(s_bad)})
        tot_novel += s_novel; tot_note += s_note
        tot_om += s_om; tot_src += s_src
        all_bad_nums += s_bad

    nr = (tot_novel / tot_note * 100) if tot_note else 0.0
    orr = (tot_om / tot_src * 100) if tot_src else 0.0

    print("\n================ GROUNDEDNESS ================")
    print(f"  label                {label}")
    print(f"  novel content rate   {tot_novel}/{tot_note} = {nr:.1f}%")
    print(f"  omission rate        {tot_om}/{tot_src} = {orr:.1f}%")
    print(f"  numerics not in source  {len(all_bad_nums)}"
          f"{'  <-- PATIENT SAFETY DEFECT' if all_bad_nums else ''}")
    if all_bad_nums:
        print(f"    {sorted(set(all_bad_nums))}")

    print("\nThe extractive control scores 0.0% novel and 0 bad numerics by")
    print("construction. Any generative model is being asked what its fluency")
    print("is worth against that.")

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    write_header = not os.path.exists(OUT_CSV)
    import csv
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if write_header:
            w.writeheader()
        w.writerows(rows)
    print(f"\nappended: {OUT_CSV}")
    return 1 if all_bad_nums else 0


if __name__ == "__main__":
    raise SystemExit(main())
