"""
SOAP rendering engines.

WHY THIS EXISTS
The supervisor asked why the project still uses Bio_ClinicalBERT rather than an
open-source LLM for SOAP suggestions. This is the seam that lets the question be
answered with a measurement instead of an opinion.

WHAT AN LLM CAN AND CANNOT FIX HERE, measured 8 Sep 2026:
Of the 39 clinical sentences in the reference consultations, the extractive
pipeline misfiles 1 on a perfect transcript (97.4%) and 7 end to end from real
audio (82.1%). Of those 7, five are ASR losses -- "fifty eight millimoles per
mole" transcribed as "58 millimetres per month" -- and two are classification
errors. A generative model addresses the two. It cannot recover words Whisper
never produced. On section placement alone the addressable gain is about 5%.

The real gain is elsewhere and the current metrics do not measure it: the
extractive note is correctly-filed sentences concatenated, whereas a clinician
writes prose. That is a genuine capability gap, and it is most likely what
"better SOAP note suggestions" means.

THE HYBRID CONTRACT
The renderer receives ONLY the sentences SOAPService.select_sections already
chose. It never sees the raw transcript. It is asked to reword, not to decide
what is clinically relevant and not to add anything.

This is deliberate. Selection is the part measured at 97.4%, so it is kept.
Generation is the part that can invent, so it is given the smallest possible
surface: it cannot import a fact from elsewhere in the conversation because it
was never shown the rest of the conversation.

WHY THE STAKES ARE HIGHER THAN THEY LOOK
The extractive renderer has a novel-content rate of 0.0% by construction --
every word is in the transcript. A generative renderer does not get that for
free, and this project has already been burned: BioGPT echoed the doctor's
greeting as the Subjective section because it performed autoregressive
completion rather than following the instruction
(app/ml/biogpt_engine.py, and the note in soap_service.generate_draft).

That is why scripts/evaluate_groundedness.py exists and why it should be run
before any model is adopted. An invented drug dose is a patient-safety defect,
not a quality regression, and fluency makes it harder to spot rather than
easier.
"""

from typing import Dict, List, Optional, Protocol, runtime_checkable

import logging

logger = logging.getLogger(__name__)


class SOAPEngineError(Exception):
    """Raised when a SOAP rendering engine is unavailable or fails."""


@runtime_checkable
class SOAPEngine(Protocol):
    """
    Anything with a matching render() satisfies this protocol.

    Same shape as ASREngine in app/ml/asr_engine.py: no base class to inherit,
    so an engine can be swapped without touching the service.
    """

    def render(self, sections: Dict[str, List[str]]) -> Dict[str, str]:
        """Selected sentences per section -> finished section text."""
        ...


class ExtractiveEngine:
    """The current renderer, wrapped so it satisfies the protocol."""

    def render(self, sections: Dict[str, List[str]]) -> Dict[str, str]:
        from app.services.soap_service import SOAPService
        return SOAPService.render_extractive(sections)


_ENGINE: Optional[SOAPEngine] = None


def get_soap_engine() -> SOAPEngine:
    """
    Returns the configured engine.

    SOAP_ENGINE=extractive  -- verbatim, cannot invent (default)
    SOAP_ENGINE=llm         -- LLM rewrites the selected sentences as prose;
                               requires LLM_MODEL_ID and transformers
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    from app.core.config import settings
    name = getattr(settings, "SOAP_ENGINE", "extractive")

    if name == "llm":
        from app.ml.llm_soap_engine import LLMSoapEngine
        _ENGINE = LLMSoapEngine.get_instance()
    elif name == "extractive":
        _ENGINE = ExtractiveEngine()
    else:
        raise SOAPEngineError(
            f"Unknown SOAP_ENGINE {name!r}. Expected 'extractive' or 'llm'."
        )

    logger.info("SOAP engine: %s", name)
    return _ENGINE


def reset_engine() -> None:
    """Drop the cached engine. For tests and for switching model at runtime."""
    global _ENGINE
    _ENGINE = None
