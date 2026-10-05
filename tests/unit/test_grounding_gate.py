"""
The grounding gate: what it catches, and the one it used to miss.

These run without a GPU, a model, or a network. LLMSoapEngine._gate is called
as an unbound method with a stub, because constructing the engine downloads
8.6 GB and loads MedGemma -- neither of which this is testing. What is being
tested is the decision logic: given some text and its source, does the section
survive or fall back?

THE CASE THAT MATTERS
On 5 October 2026 the engine ran for the first time and rendered

    "Your HbA1c has come back at fifty eight millimoles per mole"

as "The HbA1c is 5.8 mmol/mol" -- a tenfold error in a value that decides
whether a patient's diabetes is treated. The gate passed it, because every
WORD in the sentence is in the source and only the number changed. The numeric
check existed but lived in an offline script and was never wired in.
test_tenfold_lab_value_is_rejected is that exact case.
"""

from app.ml.grounding import unsupported_sentences, unsupported_values


HBA1C_SOURCE = [
    "Your blood pressure today is one thirty two over eighty four.",
    "Weight is unchanged at eighty six kilograms.",
    "Your HbA1c has come back at fifty eight millimoles per mole, "
    "which is slightly above target.",
]


# ---------------------------------------------------------------------------
# The numeric check
# ---------------------------------------------------------------------------

def test_tenfold_lab_value_is_rejected():
    """58 mmol/mol rendered as 5.8 must be caught. This is the real case."""
    note = ("The patient's blood pressure is 132/84 mmHg. Weight is 86 kg, "
            "unchanged. The HbA1c is 5.8 mmol/mol, slightly above target.")
    assert unsupported_values(note, HBA1C_SOURCE) == ["5.8"]


def test_the_word_check_alone_would_have_passed_it():
    """
    Why the numeric check had to be added rather than the threshold tuned.

    If this ever starts failing -- that is, if the word check begins rejecting
    the sentence on its own -- the numeric check is no longer load-bearing and
    somebody should find out what changed.
    """
    note = ("The patient's blood pressure is 132/84 mmHg. Weight is 86 kg, "
            "unchanged. The HbA1c is 5.8 mmol/mol, slightly above target.")
    assert unsupported_sentences(note, HBA1C_SOURCE, 0.5) == []


def test_correct_values_pass():
    note = ("The patient's blood pressure is 132/84 mmHg. Weight is 86 kg, "
            "unchanged. The HbA1c is 58 mmol/mol, slightly above target.")
    assert unsupported_values(note, HBA1C_SOURCE) == []


def test_spoken_numbers_match_their_digit_form():
    """"fifty milligrams" and "50mg" are the same dose, written two ways."""
    source = ["I am going to prescribe sumatriptan fifty milligrams for the attacks."]
    assert unsupported_values("Sumatriptan 50mg is prescribed.", source) == []


def test_an_invented_dose_is_caught():
    source = ["Take ibuprofen four hundred milligrams three times daily with food."]
    bad = unsupported_values("Take ibuprofen 4000 mg three times daily.", source)
    assert "4000" in bad


def test_adding_a_unit_is_not_treated_as_an_invented_value():
    """
    Models routinely add "mmHg" to a blood pressure. That is rewriting, not
    invention, and the gate must not fall back over it or every Objective
    section would be rejected.
    """
    source = ["Your blood pressure is one forty over ninety, which is elevated."]
    note = "The patient's blood pressure is 140/90 mmHg, which is elevated."
    assert unsupported_values(note, source) == []


# ---------------------------------------------------------------------------
# The word check
# ---------------------------------------------------------------------------

def test_an_invented_denial_is_caught():
    """The sentence two different models produced, that the prompt forbids."""
    source = ["I twisted my ankle playing football yesterday evening."]
    bad = unsupported_sentences("The patient denies any other symptoms.",
                                source, 0.5)
    assert bad and bad[0][1] == 0.0


# ---------------------------------------------------------------------------
# The gate's decision, with the model stubbed out
# ---------------------------------------------------------------------------

class _StubEngine:
    """Enough of LLMSoapEngine for _gate to run. No model, no GPU."""
    gate_enabled = True
    gate_threshold = 0.5


def _gate(text, sentences, section="objective", enabled=True):
    from app.ml.llm_soap_engine import LLMSoapEngine
    stub = _StubEngine()
    stub.gate_enabled = enabled
    return LLMSoapEngine._gate(stub, section, sentences, text)


def test_gate_falls_back_whole_section_on_a_bad_value():
    note = ("The patient's blood pressure is 132/84 mmHg. Weight is 86 kg, "
            "unchanged. The HbA1c is 5.8 mmol/mol, slightly above target.")
    out = _gate(note, HBA1C_SOURCE)
    assert "5.8" not in out
    assert "fifty eight millimoles per mole" in out


def test_gate_passes_a_faithful_rewrite():
    source = ["Pupils are equal and reactive.", "No neck stiffness."]
    note = "Pupils are equal and reactive. There is no neck stiffness."
    assert _gate(note, source) == note


def test_disabling_the_gate_returns_the_model_text_unchanged():
    """LLM_GROUNDING_GATE=false must be a real off switch, for measurement."""
    note = "The HbA1c is 5.8 mmol/mol."
    assert _gate(note, HBA1C_SOURCE, enabled=False) == note


# ---------------------------------------------------------------------------
# The renderer falls back when the engine itself fails
# ---------------------------------------------------------------------------

def test_a_failing_model_still_produces_a_note():
    """
    The worst case must be today's output, never a lost section.

    This is what makes the LLM safe to switch on: if generation raises for any
    reason -- model missing, out of memory, timeout -- the section comes back
    as the verbatim text rather than empty or broken.
    """
    from app.ml.llm_soap_engine import LLMSoapEngine

    class _Boom(_StubEngine):
        def _rewrite(self, section, sentences):
            raise RuntimeError("out of memory")

    out = LLMSoapEngine.render(_Boom(), {"objective": HBA1C_SOURCE})
    assert "fifty eight millimoles per mole" in out["objective"]
    for name in ("subjective", "assessment", "plan"):
        assert out[name], f"{name} must still carry its empty-section line"
