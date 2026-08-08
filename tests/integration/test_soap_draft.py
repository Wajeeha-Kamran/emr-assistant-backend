import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from app.ml.clinicalbert_engine import ClinicalBERTEngine, _cosine_similarity, SOAPGenerationError
from app.services.soap_service import SOAPService, FALLBACK_TEXT


# ---------------------------------------------------------------------------
# Test 1: Real ClinicalBERT embedding (verifies download, load, device)
# ---------------------------------------------------------------------------

def test_real_clinicalbert_embedding():
    """
    Loads the actual ClinicalBERT model and embeds a short clinical sentence.
    Asserts the result is a 768-dim float vector.
    """
    engine = ClinicalBERTEngine.get_instance()
    assert engine is not None
    assert engine.tokenizer is not None
    assert engine.model is not None

    embedding = engine.embed("Patient reports a headache and nausea.")
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (768,)
    assert embedding.dtype in (np.float32, np.float64)


# ---------------------------------------------------------------------------
# Test 2: Segment classification with mocked embeddings
# ---------------------------------------------------------------------------

def test_segment_classification_mocked():
    """
    Mocks ClinicalBERTEngine.embed to return predetermined vectors that
    produce known cosine similarity patterns. Asserts segments get
    classified into expected SOAP categories.
    """
    engine = ClinicalBERTEngine.get_instance()

    # Create synthetic reference embeddings (one per category, simplified)
    # We use unit vectors along different axes for clear separation
    subj_ref = np.array([1.0, 0.0, 0.0, 0.0])
    obj_ref = np.array([0.0, 1.0, 0.0, 0.0])
    asmt_ref = np.array([0.0, 0.0, 1.0, 0.0])
    plan_ref = np.array([0.0, 0.0, 0.0, 1.0])

    # Override cached reference embeddings
    original_refs = engine._ref_embeddings
    engine._ref_embeddings = {
        "subjective": [subj_ref],
        "objective": [obj_ref],
        "assessment": [asmt_ref],
        "plan": [plan_ref],
    }

    # Segment embeddings: each points mostly toward its expected category
    seg_embeddings = [
        np.array([0.9, 0.1, 0.0, 0.0]),  # -> subjective
        np.array([0.1, 0.9, 0.0, 0.0]),  # -> objective
    ]

    segments = [
        {"speaker_role": "PATIENT", "text": "I have a headache."},
        {"speaker_role": "DOCTOR", "text": "Blood pressure is normal."},
    ]

    call_count = [0]
    original_embed = engine.embed

    def mock_embed(text):
        idx = call_count[0]
        call_count[0] += 1
        return seg_embeddings[idx]

    engine.embed = mock_embed
    try:
        result = engine.classify_segments(segments)

        assert len(result["subjective"]) == 1
        assert "PATIENT: I have a headache." in result["subjective"][0]
        assert len(result["objective"]) == 1
        assert "DOCTOR: Blood pressure is normal." in result["objective"][0]
        assert len(result["assessment"]) == 0
        assert len(result["plan"]) == 0
    finally:
        engine.embed = original_embed
        engine._ref_embeddings = original_refs


# ---------------------------------------------------------------------------
# Test 3: Patient segments always go to SUBJECTIVE
# ---------------------------------------------------------------------------

def test_patient_segments_always_subjective():
    """
    Asserts all patient segments are grouped into the SUBJECTIVE section with
    the correct prefix, without classification calls.
    Also verifies punctuation joining logic.
    """
    segments = [
        {"speaker_role": "PATIENT", "text": "I have a headache"}, # no punctuation
        {"speaker_role": "PATIENT", "text": "And some nausea!"},  # has punctuation
        {"speaker_role": "PATIENT", "text": "   "},               # empty/whitespace (should be ignored)
    ]
    
    result = SOAPService.generate_draft(segments)
    
    expected_subjective = "Patient reports: I have a headache. And some nausea!"
    assert result["subjective"] == expected_subjective
    assert result["objective"] == "Not documented in dialogue."


# ---------------------------------------------------------------------------
# Test 4: Doctor segments classified into three categories
# ---------------------------------------------------------------------------

def test_doctor_segments_classified_into_three_categories(monkeypatch):
    """
    Mocks classify_doctor_segments and asserts doctor segments end up in correct 
    Objective/Assessment/Plan categories with appropriate prefixes.
    """
    mock_classified_docs = {
        "objective": ["BP 120/80", "Heart rate is normal"],
        "assessment": ["Tension headache."],
        "plan": ["Take ibuprofen"]
    }

    monkeypatch.setattr(
        ClinicalBERTEngine.get_instance(),
        "classify_doctor_segments",
        lambda docs: mock_classified_docs,
    )

    segments = [{"speaker_role": "DOCTOR", "text": "Dummy text"}]
    result = SOAPService.generate_draft(segments)

    # Note the punctuation join logic applies here too
    assert result["objective"] == "Clinician noted: BP 120/80. Heart rate is normal."
    assert result["assessment"] == "Clinical impression: Tension headache."
    assert result["plan"] == "Plan: Take ibuprofen."
    assert result["subjective"] == "Not documented in dialogue."


# ---------------------------------------------------------------------------
# Test 5: Empty sections fallback
# ---------------------------------------------------------------------------

def test_empty_sections_get_fallback(monkeypatch):
    """
    Asserts empty sections receive 'Not documented in dialogue.' and do not crash.
    """
    mock_classified_docs = {
        "objective": [],
        "assessment": [],
        "plan": []
    }

    monkeypatch.setattr(
        ClinicalBERTEngine.get_instance(),
        "classify_doctor_segments",
        lambda docs: mock_classified_docs,
    )

    segments = [{"speaker_role": "DOCTOR", "text": "Dummy text"}]
    result = SOAPService.generate_draft(segments)

    assert result["objective"] == "Not documented in dialogue."
    assert result["assessment"] == "Not documented in dialogue."
    assert result["plan"] == "Not documented in dialogue."
    assert result["subjective"] == "Not documented in dialogue."


# ---------------------------------------------------------------------------
# Test 6: Error propagation
# ---------------------------------------------------------------------------

def test_classification_error_propagation(monkeypatch):
    """
    Asserts SOAPGenerationError is raised if ClinicalBERT fails.
    """
    def mock_raise(*args, **kwargs):
        raise ValueError("Simulated classifier error")

    monkeypatch.setattr(
        ClinicalBERTEngine.get_instance(),
        "classify_doctor_segments",
        mock_raise,
    )

    segments = [{"speaker_role": "DOCTOR", "text": "Some text"}]
    
    with pytest.raises(SOAPGenerationError, match="Doctor segment classification failed"):
        SOAPService.generate_draft(segments)


# ---------------------------------------------------------------------------
# Test 7: ACCEPTANCE TEST — Real differentiated output across 3 transcripts
# ---------------------------------------------------------------------------

def test_real_differentiated_output():
    """
    Runs the three known transcripts on CPU. Asserts:
    - All four sections are present and non-empty.
    - SUBJECTIVE texts are different across transcripts.
    - Traceability Check: Asserts that patient segment text matches 
      byte-for-byte as a substring in the returned SUBJECTIVE section.
    """
    headache_segments = [
        {"speaker_role": "DOCTOR", "text": "Hello, how are you? What brings you in today?"},
        {"speaker_role": "PATIENT", "text": "I've had a really bad headache for the past two days and I feel quite nauseous."},
        {"speaker_role": "DOCTOR", "text": "Any sensitivity to light or loud noises?"},
        {"speaker_role": "PATIENT", "text": "Yes, light makes it much worse. I had to stay in a dark room yesterday."},
    ]

    ankle_segments = [
        {"speaker_role": "DOCTOR", "text": "What happened to your leg?"},
        {"speaker_role": "PATIENT", "text": "I tripped over a curb yesterday and twisted my right ankle. It's swollen and hurts to put weight on it."},
        {"speaker_role": "DOCTOR", "text": "Are you able to wiggle your toes?"},
        {"speaker_role": "PATIENT", "text": "Yes, I can wiggle them, but the ankle is very stiff."},
    ]

    chest_segments = [
        {"speaker_role": "DOCTOR", "text": "Tell me about the chest pain you are experiencing."},
        {"speaker_role": "PATIENT", "text": "It started this morning. It's a tight feeling in the middle of my chest, and I've been feeling really dizzy and lightheaded."},
        {"speaker_role": "DOCTOR", "text": "Does the pain radiate down your arm or to your back?"},
        {"speaker_role": "PATIENT", "text": "No, it's mostly staying right in the center of my chest."},
    ]

    results = []
    for label, segments in [
        ("headache", headache_segments),
        ("ankle", ankle_segments),
        ("chest", chest_segments),
    ]:
        result = SOAPService.generate_draft(segments)

        # Structural validation: all four sections present and non-empty
        for key in ["subjective", "objective", "assessment", "plan"]:
            assert key in result, f"{label}: missing '{key}' section"
            assert isinstance(result[key], str), f"{label}: '{key}' is not a string"
            assert len(result[key].strip()) > 0, f"{label}: '{key}' is empty"

        # Traceability check: EVERY patient segment must be present in the subjective output
        patient_segments = [s["text"].strip() for s in segments if s["speaker_role"] == "PATIENT" and s["text"].strip()]
        for pt_seg in patient_segments:
            # We check if the original text (minus potential punctuation changes at the very end) is in the output
            # A safe way is to check the text up to the last character if it was modified by _join_segments
            clean_pt_seg = pt_seg
            if clean_pt_seg and not clean_pt_seg[-1] in {'.', '!', '?'}:
                assert clean_pt_seg + "." in result["subjective"], (
                    f"Traceability failure: Original patient text '{clean_pt_seg}' missing from SUBJECTIVE section."
                )
            else:
                assert clean_pt_seg in result["subjective"], (
                    f"Traceability failure: Original patient text '{clean_pt_seg}' missing from SUBJECTIVE section."
                )

        results.append(result)

    # THE ACCEPTANCE CRITERION: SUBJECTIVE sections must NOT all be identical.
    subjective_texts = [r["subjective"] for r in results]
    assert len(set(subjective_texts)) > 1, (
        "REGRESSION: All three transcripts produced identical SUBJECTIVE output. "
    )
