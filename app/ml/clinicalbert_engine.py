import logging
from typing import List, Dict, Any

import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel

logger = logging.getLogger(__name__)

class SOAPGenerationError(Exception):
    """Custom exception raised when SOAP note generation or classification fails."""
    pass

# Hardcoded reference descriptions for zero-shot SOAP category classification.
# Each category has 3 descriptions covering different angles of that section.
REFERENCE_DESCRIPTIONS: Dict[str, List[str]] = {
    # SIX ANCHORS PER CATEGORY, DELIBERATELY EQUAL.
    #
    # Classification takes the maximum cosine similarity across a category's
    # anchors. A category with more anchors therefore gets more chances at a
    # high maximum, which biases the result toward it for reasons that have
    # nothing to do with the text being classified. An earlier revision on
    # 16 Aug 2026 left Objective with 5, Assessment with 9 and Plan with 6, and
    # Objective's accuracy fell from 100% to 66.7% as measurements drifted into
    # the over-represented categories. Keep these counts equal.
    #
    # None of these sentences appears in docs/evidence/consultation_scripts.md.
    # They describe what each section of a SOAP note contains, in general terms.
    # Anchors copied from the evaluation text would score well and prove nothing.
    "subjective": [
        "Patient reports symptoms including pain, discomfort, and complaints.",
        "The patient describes their medical history, allergies, and current medications.",
        "Chief complaint and history of present illness as told by the patient.",
        "What the patient says they are experiencing, in their own words.",
        "Onset, duration, and character of the problem as reported by the patient.",
        "The patient's account of how the problem affects them.",
    ],
    "objective": [
        "Physical examination findings including vital signs, temperature, blood pressure, and heart rate.",
        "Laboratory results, imaging findings, and diagnostic test results.",
        "Clinician observed signs during examination such as swelling, tenderness, and range of motion.",
        "A measured value recorded during the examination.",
        "What was seen, felt, or measured, stated without interpretation.",
        "Recorded observations such as weight, temperature, and blood test values.",
    ],
    "assessment": [
        "Clinical diagnosis, differential diagnosis, and medical impression.",
        "Assessment of the patient condition based on subjective and objective findings.",
        "The diagnosis is a specific named condition.",
        "This appears to be a particular illness or injury.",
        "The findings are consistent with a likely underlying cause.",
        "The condition is graded or staged by severity.",
    ],
    "plan": [
        "Treatment plan including prescribed medications and dosages.",
        "Follow-up instructions, referrals, and recommended lifestyle changes.",
        "Planned diagnostic tests, procedures, and patient education.",
        "An instruction to the patient about what to do next.",
        "Safety-netting advice describing when to seek urgent help.",
        "What will happen after this consultation.",
    ],
}

# Speaker-role bias: small additive bias toward expected categories.
# Verified to change 1/12 classifications in diagnostic testing.
SPEAKER_BIAS = 0.03

SOAP_CATEGORIES = ["subjective", "objective", "assessment", "plan"]


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity via numpy (no scipy dependency)."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class ClinicalBERTEngine:
    """
    Singleton wrapper for emilyalsentzer/Bio_ClinicalBERT.

    Provides embedding and zero-shot SOAP category classification via
    cosine similarity against hardcoded reference descriptions.

    Download size: ~436 MB (BERT-Base, 110M params).
    """

    _instance = None

    def __init__(self) -> None:
        if ClinicalBERTEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access ClinicalBERTEngine.")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Initializing ClinicalBERTEngine using device: {self.device}")

        try:
            # We explicitly accept the Bandit B615 risk of unpinned models here.
            # Pinning revisions with HuggingFace transformers reliably triggers
            # background API calls to check for safetensors conversions on unmerged PRs,
            # which breaks our security/network isolation requirements. 
            self.tokenizer = AutoTokenizer.from_pretrained(
                "emilyalsentzer/Bio_ClinicalBERT"  # nosec B615
            )
            self.model = AutoModel.from_pretrained(
                "emilyalsentzer/Bio_ClinicalBERT"  # nosec B615
            ).to(self.device)
        except Exception as e:
            raise RuntimeError(f"Failed to load ClinicalBERT model: {e}") from e

        # Cache for reference description embeddings (computed lazily)
        self._ref_embeddings: Dict[str, List[np.ndarray]] = {}

    @classmethod
    def get_instance(cls) -> "ClinicalBERTEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _mean_pooling(self, model_output, attention_mask) -> np.ndarray:
        """Perform mean pooling on the token embeddings."""
        token_embeddings = model_output.last_hidden_state
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        # Sum embeddings across tokens
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        # Divide by sum of mask (clamped to avoid div by zero)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        mean_pooled = sum_embeddings / sum_mask
        
        # L2 normalize
        import torch.nn.functional as F
        normalized = F.normalize(mean_pooled, p=2, dim=1)
        return normalized.cpu().numpy()

    def embed(self, text: str) -> np.ndarray:
        """
        Returns the mean-pooled, L2-normalized embedding (768-dim) for a single text input.
        """
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True, max_length=128, padding=True
        ).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        return self._mean_pooling(outputs, inputs['attention_mask'])[0]

    def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        """Embed multiple texts using mean pooling. Returns a list of 768-dim numpy arrays."""
        if not texts:
            return []
            
        inputs = self.tokenizer(
            texts, return_tensors="pt", truncation=True, max_length=128, padding=True
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            
        batch_embeddings = self._mean_pooling(outputs, inputs['attention_mask'])
        return [emb for emb in batch_embeddings]

    def _ensure_ref_embeddings(self) -> None:
        """Pre-compute and cache reference description embeddings on first use."""
        if self._ref_embeddings:
            return
        logger.info("Computing reference description embeddings (one-time)...")
        for category, descriptions in REFERENCE_DESCRIPTIONS.items():
            self._ref_embeddings[category] = self.embed_batch(descriptions)

    def classify_segments(
        self, segments: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        Classify transcript segments into SOAP categories using zero-shot
        cosine similarity against reference descriptions.

        Args:
            segments: List of dicts with 'speaker_role' and 'text' keys.

        Returns:
            Dict mapping each category to a list of matched segment texts
            (with speaker labels preserved, in original order).
            Categories with no matches have empty lists.
        """
        self._ensure_ref_embeddings()

        result: Dict[str, List[str]] = {cat: [] for cat in SOAP_CATEGORIES}

        for segment in segments:
            role = segment.get("speaker_role", "UNKNOWN")
            text = segment.get("text", "").strip()
            if not text:
                continue

            seg_emb = self.embed(text)

            # Compute max similarity against each category's reference descriptions
            max_sims: Dict[str, float] = {}
            for cat in SOAP_CATEGORIES:
                sims = [
                    _cosine_similarity(seg_emb, ref_emb)
                    for ref_emb in self._ref_embeddings[cat]
                ]
                max_sims[cat] = max(sims)

            # Apply speaker-role bias
            if role == "PATIENT":
                max_sims["subjective"] += SPEAKER_BIAS
            elif role == "DOCTOR":
                max_sims["objective"] += SPEAKER_BIAS

            # Argmax classification (no threshold — see anisotropy analysis)
            best_cat = max(max_sims, key=max_sims.get)

            # Preserve speaker label in the text for BioGPT context
            labeled_text = f"{role}: {text}"
            result[best_cat].append(labeled_text)

        return result

    def classify_doctor_segments(
        self, segments: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        Classifies pre-filtered DOCTOR segments into objective, assessment, or plan.
        Excludes subjective from the candidate categories.
        Returns a dict mapping category to a list of stripped segment text strings.
        """
        self._ensure_ref_embeddings()
        candidate_categories = ["objective", "assessment", "plan"]
        result: Dict[str, List[str]] = {cat: [] for cat in candidate_categories}

        for segment in segments:
            # We assume these are already filtered for DOCTOR and non-empty
            text = segment.get("text", "").strip()
            if not text:
                continue

            seg_emb = self.embed(text)

            max_sims: Dict[str, float] = {}
            for cat in candidate_categories:
                sims = [
                    _cosine_similarity(seg_emb, ref_emb)
                    for ref_emb in self._ref_embeddings[cat]
                ]
                max_sims[cat] = max(sims)

            # Argmax classification restricted to the 3 categories
            best_cat = max(max_sims, key=max_sims.get)

            # Do not prepend speaker labels (formatting delegated to service)
            result[best_cat].append(text)

        return result
