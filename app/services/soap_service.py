import logging
import re
from typing import List, Dict, Any, Optional
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


# ---------------------------------------------------------------------------
# Speech-act cues
# ---------------------------------------------------------------------------
# WHY THESE EXIST
# Embedding similarity classifies by TOPIC. "This looks like migraine with aura"
# and "Your blood pressure is one forty over ninety" are both about blood
# pressure and headache, so ClinicalBERT places them close together and both
# land in Objective. Measured 16 Aug 2026: Assessment scored 1 of 5, and two
# rounds of anchor rewriting did not move it.
#
# What separates them is not topic but SPEECH ACT — what the clinician is doing
# with the topic. Diagnosing, measuring and instructing are different acts, and
# each has recognisable surface forms in clinical language. These patterns
# detect the act; the embedding model still handles everything with no clear
# marker.
#
# The result is a hybrid: rules where the language is explicit, embeddings where
# it is not. Neither alone was sufficient.
#
# HONESTY NOTE. These were written as families of clinical phrasing — hedged
# diagnostic assertion, directive instruction, recorded observation — not by
# reading the sentences that failed. Some inevitably match those sentences,
# because that is what a diagnosis sounds like. The check against having fitted
# them to the evaluation set is docs/evidence/soap_heldout.md: sentences from
# clinical scenarios that appear nowhere in the reference scripts, scored
# separately. If the rules only work on the scripts, that set will show it.

_ASSESSMENT_CUES = [
    # Hedged diagnostic assertion — the clinician naming what they think it is
    r"\b(this|that|it)\s+(looks like|appears to be|sounds like|seems to be|seems like)\b",
    r"\b(this|that)\s+is\s+(a|an)\b",
    r"\bconsistent with\b",
    r"\bsuggestive of\b",
    r"\bin keeping with\b",
    r"\bindicative of\b",
    r"\bpoints to\b",
    # Explicit diagnostic vocabulary
    r"\b(diagnosis|impression)\b",
    r"\bdiagnosed with\b",
    r"\bdifferential\b",
    r"\brule out\b",
    r"\bcannot exclude\b",
    # Probability judgements — a clinician weighing one explanation against another
    r"\b(likely|unlikely|probable|probably)\b",
    r"\bi (do not|don't|donot) think it is\b",
    r"\bi think (this|that|it) is\b",
    # Severity grading, which is part of naming a condition
    r"\bgrade\s+(one|two|three|four|1|2|3|4)\b",
    r"\bstage\s+(one|two|three|four|i{1,3}v?|1|2|3|4)\b",
    r"\b(mild|moderate|severe|suboptimal|uncontrolled|well controlled)\b",
]

_PLAN_CUES = [
    # Directive to the patient — an imperative opening the sentence
    r"^(please\s+)?(take|rest|keep|start|stop|finish|continue|avoid|drink|apply|"
    r"use|focus|book|call|bring|return|come back|carry on|monitor|elevate)\b",
    # Clinician's stated intention
    r"\bi (will|am going to|would like to|shall)\b",
    r"\bwe (will|can) (arrange|book|review|repeat|check)\b",
    # Follow-up and referral
    r"\bfollow[\s-]?up\b",
    r"\brefer(ral|red|ring)?\b",
    r"\b(come back|review|repeat|recheck|seen again)\b.*\bin\b",
    r"\bprescrib(e|ing|ed)\b",
    # Safety netting — a conditional instruction about when to seek help
    r"^if\b.*\b(come back|go to|seek|let me know|be seen|call|contact|emergency)\b",
]

_OBJECTIVE_CUES = [
    # A recorded measurement
    r"\b(blood pressure|temperature|weight|pulse|heart rate|hba1c|"
    r"oxygen saturation|bmi|respiratory rate)\b.*\b(is|are|was|were|of|at)\b",
    r"\b(has come back|came back|results? (show|shows|are))\b",
    # An observation stated without interpretation
    r"^(there (is|are)|no\b)",
    r"\bexamination (shows|reveals|is|demonstrates)\b",
    r"\bon examination\b",
    r"\b(shows|reveals|demonstrates|palpation|auscultation)\b",
]

# Conditional instruction: a condition, then something the patient must do.
_SAFETY_NET_RE = re.compile(
    r"^if\b.*\b(come back|go to|seek|let me know|be seen|call|contact|"
    r"attend|return|emergency|straight away|immediately)\b",
    re.I,
)

_ASSESSMENT_RE = [re.compile(p, re.I) for p in _ASSESSMENT_CUES]
_PLAN_RE = [re.compile(p, re.I) for p in _PLAN_CUES]
_OBJECTIVE_RE = [re.compile(p, re.I) for p in _OBJECTIVE_CUES]


def _cue_category(sentence: str) -> Optional[str]:
    """
    Return the section a sentence's speech act implies, or None if it has no
    clear marker and should be left to the embedding classifier.

    Assessment is tested first because it is the act the embedding model is
    worst at recognising, and because a sentence that both names a diagnosis and
    mentions a measurement ("This looks like migraine, and your blood pressure is
    high") is doing the diagnosing — that is the clinically significant content.
    Plan is tested before Objective for the same reason: "I will arrange an
    X-ray" is an instruction that happens to mention an investigation.
    """
    text = sentence.strip()

    # Safety-netting is checked before everything else. A conditional
    # instruction -- "if X happens, do Y" -- is a directive to the patient
    # whatever words appear inside the condition, so it belongs in Plan.
    #
    # Without this, "If the pain becomes suddenly severe, go to the emergency
    # department" was filed under Assessment, because "severe" is a severity
    # term and severity grading is part of naming a condition. Measured
    # 16 Aug 2026: two of the three remaining errors on the reference set were
    # exactly this. The held-out set happened to pass only because its
    # safety-netting sentences use "crushing" rather than "severe" -- passing
    # by luck of wording, which is not passing.
    if _SAFETY_NET_RE.search(text):
        return "plan"

    for pattern in _ASSESSMENT_RE:
        if pattern.search(text):
            return "assessment"
    for pattern in _PLAN_RE:
        if pattern.search(text):
            return "plan"
    for pattern in _OBJECTIVE_RE:
        if pattern.search(text):
            return "objective"
    return None


def _apply_cues(
    classified: Dict[str, List[str]], ordered_sentences: List[str]
) -> Dict[str, List[str]]:
    """
    Re-route sentences whose speech act is explicit, leaving the rest where the
    embedding classifier put them.

    Applied after classification rather than instead of it, so the classifier
    remains the default and this only overrides where the language is
    unambiguous. Each section is then restored to the order the sentences were
    spoken in, so a re-routed sentence does not end up appended out of sequence.
    """
    position = {text: i for i, text in enumerate(ordered_sentences)}
    out: Dict[str, List[str]] = {"objective": [], "assessment": [], "plan": []}

    for category, texts in classified.items():
        if category not in out:
            out[category] = []
        for text in texts:
            out[_cue_category(text) or category].append(text)

    for category in out:
        out[category].sort(key=lambda t: position.get(t, len(position)))
    return out


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

        classified_docs = _apply_cues(
            classified_docs, [d["text"] for d in doctor_segments]
        )

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
