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
