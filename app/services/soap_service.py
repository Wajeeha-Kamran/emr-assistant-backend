import logging
from typing import List, Dict, Any
from app.ml.clinicalbert_engine import ClinicalBERTEngine, SOAPGenerationError

logger = logging.getLogger(__name__)

FALLBACK_TEXT = "Not documented in dialogue."


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

        # Extract and strip patient texts
        patient_texts = [
            s.get("text", "").strip() 
            for s in segments 
            if s.get("speaker_role") == "PATIENT" and s.get("text", "").strip()
        ]

        # Extract, strip, and pass valid doctor segments
        doctor_segments = [
            {"speaker_role": "DOCTOR", "text": s.get("text", "").strip()}
            for s in segments
            if s.get("speaker_role") == "DOCTOR" and s.get("text", "").strip()
        ]

        try:
            classifier = ClinicalBERTEngine.get_instance()
            classified_docs = classifier.classify_doctor_segments(doctor_segments)
        except Exception as e:
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
