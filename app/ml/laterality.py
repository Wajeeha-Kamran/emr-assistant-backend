"""
Left and right, which the embeddings cannot see.

MEASURED 5 OCTOBER 2026
For the Assessment "Patient twisted their right ankle while playing
basketball. Swelling and tenderness observed.", searched against the 70-code
reference set:

    M25.572  Pain in LEFT ankle and joints of left foot     0.9022
    M25.571  Pain in RIGHT ankle and joints of right foot   0.9009

A gap of 0.0013 between two codes describing opposite limbs is not a ranking,
it is noise. Bio_ClinicalBERT was never trained to treat "left" and "right" as
opposites, and mean-pooling token vectors across a whole sentence buries the
contribution of one word. Asking the model to do better is not a tuning
problem; the information is not in the representation.

So laterality is decided by reading the words instead. A code describing the
opposite side of the body from the one the note names is ranked below every
code that does not contradict the note. Within each group the similarity order
is untouched.

WHAT THIS DOES NOT FIX
Two other weaknesses were measured in the same run and are unaffected:
symptom codes outrank injury codes (M25.57x "pain" beats S93.4 "sprain" by
0.026 for a described twist), and every score sits between 0.85 and 0.90, so
"Dizziness and giddiness" scores 0.8690 against an ankle note. Both are
recorded in the report as limitations of mean-pooled embeddings. This module
fixes one thing only, and claiming otherwise would overstate it.

NO THRESHOLD, DELIBERATELY
There is no penalty constant and no cut-off here. A contradicting code sorts
after a non-contradicting one; that is the whole rule. Nothing in this file
can be tuned to flatter a result.
"""

import re
from typing import Optional

_LEFT = re.compile(r"\bleft\b", re.IGNORECASE)
_RIGHT = re.compile(r"\bright\b", re.IGNORECASE)

# "Come back right away" names no side. These are the adverbial uses of
# "right" that turn up in dictated consultation text; without stripping them,
# a Plan section ending "call us right away" would demote every left-sided
# code in the catalogue. "Left" has no equivalent problem -- it is a direction
# or a past tense ("the pain left"), and the past tense is rare enough in
# clinical notes to ignore rather than guess at.
_NON_ANATOMICAL = re.compile(
    r"\bright (?:away|now|here|there|back)\b"
    r"|\ball\s+right\b"
    r"|\bthat'?s\s+right\b",
    re.IGNORECASE,
)


def side_of(text: str) -> Optional[str]:
    """
    "left", "right", or None.

    None when the text names both sides or neither. Both is deliberate: a note
    covering a right ankle and a left knee rules nothing out, and treating it
    as right-sided would discard the knee code.
    """
    if not text:
        return None
    cleaned = _NON_ANATOMICAL.sub(" ", text)
    has_left = bool(_LEFT.search(cleaned))
    has_right = bool(_RIGHT.search(cleaned))
    if has_left == has_right:
        return None
    return "left" if has_left else "right"


def contradicts(note_text: str, code_description: str) -> bool:
    """
    True when the code is for the opposite side from the one the note names.

    False whenever either side is unknown, so a code is only ever demoted on
    positive evidence that it is wrong.
    """
    note_side = side_of(note_text)
    if note_side is None:
        return False
    code_side = side_of(code_description)
    if code_side is None:
        return False
    return note_side != code_side
