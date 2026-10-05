"""
The left/right filter on code suggestions.

No model, no database, no network -- this is word reading, which is the whole
point of it existing. See app/ml/laterality.py for the measurement that
prompted it: the embeddings put "Pain in LEFT ankle" 0.0013 above "Pain in
RIGHT ankle" for a note about a right ankle.
"""

from app.ml.laterality import contradicts, side_of


# ---------------------------------------------------------------------------
# Reading a side out of the text
# ---------------------------------------------------------------------------

def test_a_single_side_is_read():
    assert side_of("Pain in right ankle and joints of right foot") == "right"
    assert side_of("Sprain of unspecified ligament of left ankle") == "left"


def test_no_side_mentioned():
    assert side_of("Essential (primary) hypertension") is None
    assert side_of("") is None


def test_both_sides_mean_no_side():
    """
    A note covering two limbs must not rule either of them out.

    If this returned "right", the left knee code would be demoted for a note
    that explicitly describes a left knee.
    """
    assert side_of("Twisted the right ankle and bruised the left knee") is None


def test_right_away_is_not_a_side():
    """
    Dictated plans end like this constantly. Counting it as anatomical would
    demote every left-sided code in the catalogue on a note that named no side
    at all.
    """
    assert side_of("Come back right away if the swelling worsens.") is None
    assert side_of("Call the surgery right now if it gets worse.") is None


# ---------------------------------------------------------------------------
# The contradiction rule
# ---------------------------------------------------------------------------

NOTE = ("Patient twisted their right ankle while playing basketball. "
        "Swelling and tenderness observed.")


def test_the_measured_case():
    """The exact pair that scored 0.9022 (left) against 0.9009 (right)."""
    assert contradicts(NOTE, "Pain in left ankle and joints of left foot")
    assert not contradicts(NOTE, "Pain in right ankle and joints of right foot")


def test_a_code_with_no_side_is_never_demoted():
    assert not contradicts(NOTE, "Essential (primary) hypertension")
    assert not contradicts(NOTE, "Dizziness and giddiness")


def test_a_note_with_no_side_demotes_nothing():
    """Only positive evidence demotes. Silence is not evidence."""
    plain = "Patient reports a persistent headache for three days."
    assert not contradicts(plain, "Pain in left ankle and joints of left foot")
    assert not contradicts(plain, "Pain in right ankle and joints of right foot")


def test_a_note_naming_both_sides_demotes_nothing():
    both = "Twisted the right ankle and bruised the left knee."
    assert not contradicts(both, "Pain in left knee")
    assert not contradicts(both, "Pain in right ankle and joints of right foot")


# ---------------------------------------------------------------------------
# What the filter does to the ranking
# ---------------------------------------------------------------------------

def test_the_ordering_rule_reproduces_the_measured_fix():
    """
    The scores below are the real ones, recorded on 5 October 2026 against the
    70-code reference set. Sorting them the way search_codes now does must put
    the right-sided codes first without reordering anything inside each group.
    """
    measured = [
        ("Pain in left ankle and joints of left foot", 0.9022),
        ("Pain in right ankle and joints of right foot", 0.9009),
        ("Sprain of unspecified ligament of left ankle, initial encounter", 0.8769),
        ("Sprain of unspecified ligament of right ankle, initial encounter", 0.8763),
        ("Pain in right knee", 0.8725),
        ("Dizziness and giddiness", 0.8690),
    ]
    ordered = sorted(measured, key=lambda p: (contradicts(NOTE, p[0]), -p[1]))
    assert [d for d, _ in ordered[:4]] == [
        "Pain in right ankle and joints of right foot",
        "Sprain of unspecified ligament of right ankle, initial encounter",
        "Pain in right knee",
        "Dizziness and giddiness",
    ]
    # The left-sided codes keep their relative order; they are demoted, not
    # discarded, because nothing here is certain enough to throw a code away.
    assert [d for d, _ in ordered[4:]] == [
        "Pain in left ankle and joints of left foot",
        "Sprain of unspecified ligament of left ankle, initial encounter",
    ]
