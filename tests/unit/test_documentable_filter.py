"""
The sentence filter that decides what reaches a note at all.

These tests exist because of a defect found on 12 September 2026. The four
scripted reference consultations are written in full sentences, so the filter
looked complete when measured against them: 0.0% noise. Run against the five
Kaggle recordings -- real, unscripted speech -- it let 299 of 677 sentences
through that were nothing but acknowledgement. CAR0001's Objective section was
25 bare "No."s.

The last test is the important one. It reads the labelled ground truth and
asserts that no sentence a clinician labelled Objective, Assessment or Plan is
ever discarded. Without it, tightening this filter could quietly improve the
noise rate by throwing away clinical content, and the headline accuracy figure
would not notice.
"""

import os
import re

import pytest

from app.services.soap_service import _is_backchannel, _is_documentable


BACKCHANNEL = [
    "Okay.",
    "OK.",
    "All right.",
    "No.",
    "Yeah.",
    "Yes.",
    "Nope.",
    "None.",
    "Sure.",
    "I see.",
    "Mm.",
    "Uh,",
    "Oh, okay.",
    "Sure, yeah.",
    "Yeah, I do actually.",
    "Um, so, yeah.",
    "I think so.",
    "Uh, never.",
]

DOCUMENTABLE = [
    # Short answers that still name something
    "No muscle weakness.",
    "No strokes.",
    "Barely.",
    "Swollen.",
    "No, nothing like that.",
    "Not that I've heard.",
    # Anything carrying a number, however filler-like the words around it
    "52. Okay, okay.",
    # Ordinary clinical content
    "There is swelling over the lateral malleolus and tenderness on the outer side.",
    "Your blood pressure is one forty over ninety, which is elevated.",
    "Take ibuprofen four hundred milligrams three times daily with food.",
]


@pytest.mark.parametrize("sentence", BACKCHANNEL)
def test_backchannel_is_not_documentable(sentence):
    assert _is_backchannel(sentence) is True
    assert _is_documentable(sentence) is False


@pytest.mark.parametrize("sentence", DOCUMENTABLE)
def test_content_survives(sentence):
    assert _is_backchannel(sentence) is False
    assert _is_documentable(sentence) is True


def test_a_number_is_always_content():
    """
    "52. Okay, okay." answers "how old are you". Every letter in it is a filler
    word, so a purely lexical rule discards the patient's age.
    """
    assert _is_backchannel("Okay, okay.") is True
    assert _is_backchannel("52. Okay, okay.") is False


def test_questions_and_pleasantries_still_excluded():
    """The three older rules are unaffected by the backchannel rule."""
    assert _is_documentable("Have you had a fever?") is False
    assert _is_documentable("Let me check your blood pressure.") is False
    assert _is_documentable("Good morning.") is False


_LABEL_LINE = re.compile(r"^([OAPX])\s*\|\s*(.+?)\s*$")
_EVIDENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "evidence",
)


def _labelled():
    for name in ("soap_expected.md", "soap_heldout.md"):
        path = os.path.join(_EVIDENCE, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = _LABEL_LINE.match(line.strip())
                if match:
                    yield name, match.group(1), match.group(2)


def test_no_labelled_clinical_sentence_is_discarded():
    """
    Every sentence labelled O, A or P by hand must reach the note.

    This is what makes it safe to tighten the filter: if a change starts
    discarding real findings, this fails before the accuracy figure moves.
    """
    labelled = list(_labelled())
    assert len(labelled) >= 100, "ground-truth files did not parse"

    discarded = [
        (name, label, sentence)
        for name, label, sentence in labelled
        if label != "X" and not _is_documentable(sentence)
    ]
    assert discarded == []
