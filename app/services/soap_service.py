import logging
import re
from typing import List, Dict, Any
from app.ml.clinicalbert_engine import ClinicalBERTEngine, SOAPGenerationError

logger = logging.getLogger(__name__)

FALLBACK_TEXT = "Not documented in dialogue."

# Split on sentence-ending punctuation followed by whitespace. The negative
# lookbehind/lookahead on digits keeps "38.2" and "one 140.90" intact, which
# matters because ASR writes measurements as digits.
_SENTENCE_SPLIT = re.compile(r"(?<![0-9])([.!?]+)(?![0-9])\s+")

# An announcement of an action about to be taken. "Let me examine you" documents
# nothing; the findings it introduces are in the sentences that follow, and those
# are classified on their own merits.
_ANNOUNCEMENT = re.compile(r"^(let me|let us|let's|i'?ll just|i am going to have a look)\b", re.I)

# Social speech carrying no clinical content. Kept as an explicit, readable list
# rather than a similarity threshold: a threshold would have to be tuned, and
# tuning it against the same four scripts the system is measured on would make
# the measurement meaningless. These are structural properties of conversation,
# not fitted parameters.
_PLEASANTRY = re.compile(
    r"^(good morning|good afternoon|good evening|good day|hello|hi\b|hey\b"
    r"|please take a seat|take a seat|come in|have a seat|thank you|thanks"
    r"|understood|okay$|ok$|alright$|right$|no problem|you'?re welcome"
    r"|see you|goodbye|bye)\b",
    re.I,
)


def _split_sentences(text: str) -> List[str]:
    """
    Split a block of speech into sentences, KEEPING terminal punctuation.

    Keeping the punctuation is not cosmetic. An earlier version stripped it here,
    which silently disabled the question filter below -- it tests for a trailing
    "?" that had already been removed, so every question the doctor asked still
    reached the note. Measured 16 Aug 2026: noise fell only from 100% to 73.5%,
    and the remainder was entirely questions.
    """
    parts = _SENTENCE_SPLIT.split(text)
    out: List[str] = []
    # re.split with a capturing group yields [text, delim, text, delim, ..., text]
    for i in range(0, len(parts), 2):
        body = parts[i].strip()
        if not body:
            continue
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((body + delim).strip())
    return out


def _is_documentable(sentence: str) -> bool:
    """
    True if a sentence belongs in a clinical note at all.

    Three kinds of speech are excluded, and none of them is a judgement call
    about clinical importance -- they are all structural.

    QUESTIONS. "Have you had a fever?" documents nothing. The patient's answer
    is what gets recorded, and that already reaches Subjective from the PATIENT
    side of the transcript. Before this filter, every doctor question in the
    reference scripts appeared in the note: Objective opened with "Can you
    describe the pain for me?".

    ANNOUNCEMENTS. "Let me examine you" states an intention, not a finding.

    PLEASANTRIES. Greetings and thanks. Before this filter, "Good morning" and
    "Please take a seat" were filed under Plan.

    Measured on the four reference scripts (16 Aug 2026), 34 of 34 non-clinical
    sentences reached the note before this existed -- a 100% noise rate.
    """
    text = sentence.strip()
    if not text:
        return False
    if text.rstrip().endswith("?"):
        return False
    if _ANNOUNCEMENT.match(text):
        return False
    if _PLEASANTRY.match(text):
        return False
    return True


class SOAPService:
    @staticmethod
    def generate_draft(
        segments: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Generates a structured SOAP note from diarized transcript segments
        using a purely extractive pipeline.

        Stage 1: PATIENT segments go directly to SUBJECTIVE.
        Stage 2: DOCTOR segments are classified into OBJECTIVE, ASSESSMENT,
                 or PLAN via ClinicalBERT zero-shot similarity.

        Returns a dictionary containing:
        {
            "subjective": str,
            "objective": str,
            "assessment": str,
            "plan": str
        }
        """
        # NOTE: BioGPT (app/ml/biogpt_engine.py) is intentionally NOT called here.
        # Testing showed BioGPT's rephrasing step did not follow instructions — it
        # performed autoregressive completion instead, producing output unrelated to
        # the extracted content (e.g. echoing the doctor's greeting as the Subjective
        # section). The extractive-only approach guarantees every word in the output
        # is traceable to the actual transcript. BioGPT engine is retained in the
        # codebase for potential future use with fine-tuning.

        # Speech is split into sentences before anything else happens.
        #
        # WHY. Classification assigns one category per item, by argmax. A single
        # Whisper segment routinely contains a whole clinical sequence: on the
        # live run of 15 Aug 2026, one 30-second segment held the examination
        # findings, the diagnosis AND the entire treatment plan, so all of it was
        # filed under Objective and Assessment came back empty. A sentence is the
        # smallest unit that carries one clinical meaning, so it is the right
        # unit to classify.
        patient_texts = [
            sentence
            for seg in segments
            if seg.get("speaker_role") == "PATIENT"
            for sentence in _split_sentences(seg.get("text", "").strip())
            if _is_documentable(sentence)
        ]

        doctor_segments = [
            {"speaker_role": "DOCTOR", "text": sentence}
            for seg in segments
            if seg.get("speaker_role") == "DOCTOR"
            for sentence in _split_sentences(seg.get("text", "").strip())
            if _is_documentable(sentence)
        ]

        try:
            classifier = ClinicalBERTEngine.get_instance()
            
            # Use concurrent.futures to enforce the NLP timeout budget
            # Note: The underlying thread will continue if it times out, but the caller gets a timely error
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
            from app.core.metrics import metrics
            
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(classifier.classify_doctor_segments, doctor_segments)
                try:
                    from app.core.config import settings
                    classified_docs = future.result(timeout=settings.NLP_TIMEOUT_SECONDS)
                    metrics.record_metric("soap_generation", True)
                except FuturesTimeoutError:
                    metrics.record_metric("soap_generation", False)
                    from fastapi import HTTPException
                    logger.warning("ClinicalBERT inference timed out. Underlying thread continues.")
                    raise HTTPException(
                        status_code=503, 
                        detail="NLP Engine Timeout", 
                        headers={"Retry-After": "5"}
                    )
            finally:
                executor.shutdown(wait=False)
                    
        except Exception as e:
            from fastapi import HTTPException
            if isinstance(e, HTTPException):
                raise
            metrics.record_metric("soap_generation", False)
            raise SOAPGenerationError(
                f"Doctor segment classification failed: {e}"
            ) from e

        def _join_segments(texts: List[str]) -> str:
            if not texts:
                return ""
            cleaned = []
            for t in texts:
                t = t.strip()
                if not t:
                    continue
                # Add terminal punctuation if missing
                if not t[-1] in {'.', '!', '?'}:
                    t += "."
                cleaned.append(t)
            return " ".join(cleaned)

        result = {}

        # Subjective (Patient only)
        if patient_texts:
            result["subjective"] = "Patient reports: " + _join_segments(patient_texts)
        else:
            result["subjective"] = FALLBACK_TEXT

        # Objective
        if classified_docs.get("objective"):
            result["objective"] = "Clinician noted: " + _join_segments(classified_docs["objective"])
        else:
            result["objective"] = FALLBACK_TEXT

        # Assessment
        if classified_docs.get("assessment"):
            result["assessment"] = "Clinical impression: " + _join_segments(classified_docs["assessment"])
        else:
            result["assessment"] = FALLBACK_TEXT

        # Plan
        if classified_docs.get("plan"):
            result["plan"] = "Plan: " + _join_segments(classified_docs["plan"])
        else:
            result["plan"] = FALLBACK_TEXT

        return result
