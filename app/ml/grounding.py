"""
Is every sentence in this note supported by the transcript?

WHY THIS EXISTS
Extraction cannot invent: every word it emits came from the transcript. A
generative renderer gives that up, and the loss is not theoretical.

Measured 11 September 2026, four scripted consultations, prompt v2:

    MedGemma 4B  "The patient denies any other symptoms."
    Mistral 7B   "The patient denies any history of fractures or dislocations."

Both in script 2's Subjective. Nothing in that consultation resembles either
sentence. They are invented pertinent negatives -- assertions that the patient
was asked something and answered, which never happened. Two unrelated model
families produced the same class of fabrication in the same place.

WHY THIS IS CODE AND NOT A BETTER PROMPT
Because the prompt was tried. v2 added:

    Do not state that anything was denied, normal, absent, unremarkable or not
    present unless the sentences below say so. An absence is a clinical finding
    and inventing one is the same as inventing a symptom.

MedGemma produced the identical sentence anyway, word for word. The pull of
clinical-note convention beat the instruction. An instruction is a request; a
check is a guarantee, and this is the same principle as the diarizer's fallback
chain -- the system verifies rather than trusts.

WHAT IT CANNOT DO
It catches sentences with no source. It does NOT catch a sentence that borrows
the right words and changes their meaning -- MedGemma's v1 inversion, "not as
severe as they usually are" from "Not this bad", would pass this check
untouched because every word in it is sourced. That needs entailment. The
polarity list in scripts/evaluate_groundedness.py exists for exactly that gap.
"""

import re
from typing import Dict, List, Tuple

WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
SENTENCE_SPLIT = re.compile(r"(?<![0-9])([.!?]+)(?![0-9])\s+")

# Words that carry no clinical content, so their presence or absence says
# nothing about whether a claim is supported. The section lead-ins the
# extractive renderer adds are here too, for the same reason.
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
    """Crude suffix strip, enough that swollen and swelling do not read as new."""
    for suf in ("ational", "ation", "ings", "ing", "edly", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(text: str) -> List[str]:
    return [stem(w) for w in WORD_RE.findall((text or "").lower())
            if w not in STOPWORDS and len(w) > 2]


def split_sentences(text: str) -> List[str]:
    out, parts = [], SENTENCE_SPLIT.split(text or "")
    buf = ""
    for part in parts:
        if part is None:
            continue
        if re.fullmatch(r"[.!?]+", part):
            buf += part
            out.append(buf.strip())
            buf = ""
        else:
            buf += part
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


def support(sentence: str, source_sentences: List[str]) -> float:
    """
    Fraction of this sentence's clinical words that appear anywhere in source.

    Deliberately generous: the words may come from ANY of the source
    sentences, in any order. A rewrite that merges two source sentences is
    legitimate and must not be flagged. What cannot happen legitimately is a
    sentence whose clinical content appears nowhere at all.
    """
    words = content_words(sentence)
    if not words:
        return 1.0            # punctuation or filler: nothing to support
    pool = set()
    for src in source_sentences or []:
        pool.update(content_words(src))
    if not pool:
        return 0.0
    return sum(1 for w in words if w in pool) / len(words)


DEFAULT_THRESHOLD = 0.5


def unsupported_sentences(text: str, source_sentences: List[str],
                          threshold: float = DEFAULT_THRESHOLD
                          ) -> List[Tuple[str, float]]:
    """
    Sentences whose clinical content the source does not carry.

    WHERE 0.5 COMES FROM, measured on the real notes:

        0.00  MedGemma  "The patient denies any other symptoms."
        0.00  Mistral   "The patient denies any history of fractures..."
        0.33  MedGemma  "not as severe as they usually are"  (the v1 inversion)
        ----  nothing observed between 0.33 and 0.67 ----
        0.67  "reports a bit of nausea yesterday morning, but denies being sick"
        0.80  "will be prescribed sumatriptan fifty milligrams for the attacks"
        0.86  "mention having sprained the same ankle about two years ago"

    0.5 sits in the middle of that empty band. The inversion falling on the
    flagged side is a bonus rather than the design -- this check cannot detect
    inversions in general, because an inversion reuses the source's words.

    CAVEAT WORTH STATING: that is six sentences. The band is wide and the two
    groups are far apart, but a threshold chosen by looking at the data it will
    be judged on is fitted, and six points is not many. This is why the gate
    logs every sentence it rejects and why rejection costs prose rather than
    content -- see LLMSoapEngine.render. A wrong call is visible and cheap.
    """
    out = []
    for sentence in split_sentences(text):
        score = support(sentence, source_sentences)
        if score < threshold:
            out.append((sentence, round(score, 2)))
    return out


# ---------------------------------------------------------------------------
# Numeric fidelity
# ---------------------------------------------------------------------------
# WHY THIS LIVES HERE NOW
# This code used to sit in scripts/evaluate_groundedness.py, an offline
# analysis script, so the deployed gate never ran it. On 5 October 2026 the
# engine was executed for the first time and MedGemma rendered
#
#     "Your HbA1c has come back at fifty eight millimoles per mole"
#
# as "The HbA1c is 5.8 mmol/mol". A tenfold error in a value that decides
# treatment, and the word-overlap check passed it -- every word in the
# sentence IS in the source; only the number changed.
#
# Word support and numeric fidelity are different questions. The gate now asks
# both. One implementation, imported by the engine and by the evaluation
# script, because duplicated metric code is how two earlier measurement bugs
# happened.

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


def _merge_pairs(run: List[str]) -> List[int]:
    """
    Group a run of number words the way a speaker means them.

        one thirty two  ->  [1, 32]
        one forty       ->  [1, 40]
        eighty four     ->  [84]
        fifty eight     ->  [58]

    A tens word followed by a ones word is one number, not two. Without this,
    "one thirty two" concatenates as 1|30|2 = "1302" and never produces 132 --
    which is how a correctly transcribed blood pressure of 132/84 came to be
    reported as an invented number by the first version of this file.
    """
    vals, i = [], 0
    while i < len(run):
        w = run[i]
        if (w in _TENS and i + 1 < len(run)
                and run[i + 1] in _ONES and _ONES[run[i + 1]] < 10):
            vals.append(_TENS[w] + _ONES[run[i + 1]])
            i += 2
        elif w in _ONES:
            vals.append(_ONES[w]); i += 1
        elif w in _TENS:
            vals.append(_TENS[w]); i += 1
        elif w in _SCALES:
            vals.append(_SCALES[w]); i += 1
        else:
            i += 1
    return vals


def _run_values(run: List[str]) -> List[str]:
    """
    Every value a run of number words could plausibly mean.

    Deliberately generous. "one forty over ninety" is spoken blood pressure;
    the textbook composer reads it as 41, a reader hears 140. Rather than
    guess, the run yields the spoken reading, the composed value, and each
    word's own value -- so 140 is accepted as sourced.

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

    merged = _merge_pairs(run)
    out = ["".join(_fmt(v) for v in merged)] if merged else []

    total = current = 0
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
    out += [_fmt(v) for v in merged]
    return out


def numeric_facts(text: str) -> set:
    """Normalised numbers and units. Comparable across word and digit forms."""
    text = (text or "").lower()

    # "50mg" is one token to a word-level tokeniser, and it matches neither the
    # digit pattern nor the unit list, so it was silently discarded -- the dose
    # was neither credited nor checked. A model writing "500mg" instead of
    # "500 mg" would have walked past the values-not-in-source check entirely.
    #
    # Not hypothetical: Mistral 7B writes "sumatriptan 50mg" by default, so the
    # one check in this file that exists for patient safety was blind to the
    # exact formatting the model under test happens to prefer.
    text = re.sub(r"(\d)\s*([a-z])", r"\1 \2", text)

    tokens = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text)
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


def unsupported_values(text: str, source_sentences: List[str]) -> List[str]:
    """
    Numbers in TEXT that the source never says.

    Returns the offending values, normalised. Empty list means every number in
    the note came from the transcript.

    This is deliberately separate from support(). A sentence can be entirely
    supported word for word and still carry a wrong number:

        source  "Your HbA1c has come back at fifty eight millimoles per mole"
        note    "The HbA1c is 5.8 mmol/mol"

    support() scores that near 1.0, because patient, hba1c, mmol and target
    are all present. The only thing that changed is the one token that decides
    whether the patient's diabetes is controlled.

    Units are excluded from the comparison. numeric_facts() emits unit tokens
    alongside values, and a model adding "mmHg" to a blood pressure or "mg" to
    a dose is normal rewriting, not invention -- the unit question is tracked
    separately (an invented "Fahrenheit" is caught by support(), because the
    word itself has no source). Only values are checked here, so this does not
    fire on correct prose.
    """
    note_facts = {f for f in numeric_facts(text) if DIGITS_RE.match(str(f))}
    src_facts = {f for f in numeric_facts(" ".join(source_sentences))
                 if DIGITS_RE.match(str(f))}
    return sorted(note_facts - src_facts)
