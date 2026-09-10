"""
Instruction-tuned LLM renderer for SOAP sections.

It receives only the sentences the extractive classifier already selected for
one section, and rewrites them as clinical prose. It never sees the raw
transcript. See app/ml/soap_engine.py for why the seam is placed there.

MODEL CHOICE
Set LLM_MODEL_ID to any instruction-tuned causal LM. The candidates named by
the supervisor, in the order worth trying:

    google/medgemma-4b-it              smallest; the only one with a plausible
                                       CPU future on this hardware
    <medinote-7b-instruct>             purpose-built for clinical notes from
                                       dialogue -- the closest task match
    meta-llama/Meta-Llama-3-8B-Instruct  general, strong instruction following;
                                       the control for "does medical tuning
                                       actually help here"
    mistralai/Mistral-7B-Instruct-v0.3   same role, cheaper

A WARNING ABOUT MEDITRON 7B, which is also on that list. epfl-llm/meditron-7b
is a BASE model: continued pretraining on medical text, no instruction tuning.
That is the same shape as the failure this project already had, recorded in
app/ml/biogpt_engine.py -- BioGPT ignored the instruction and performed
autoregressive completion instead. Use an instruction-tuned fine-tune of it, or
include it deliberately to demonstrate why instruction tuning is the property
that matters. Do not include it expecting it to work.

DETERMINISM
Sampling is off. do_sample=False with temperature unset makes generation greedy
and reproducible, which is a precondition for a measurement anyone can re-run
and for the groundedness figures meaning anything across runs.
"""

import logging
import re
import threading
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_INFERENCE_LOCK = threading.Lock()

SECTION_BRIEF = {
    "subjective": "the patient's own account of the problem",
    "objective": "the clinician's examination findings and measurements",
    "assessment": "the clinician's diagnosis or clinical impression",
    "plan": "the treatment, prescriptions and follow-up",
}

PROMPT = """You are helping a doctor write the {section} section of a SOAP note.

The {section} section records {brief}.

Below are the sentences already selected for this section, taken verbatim from
a consultation recording. Rewrite them as one short, clinical paragraph.

Rules:
- Use ONLY the information in the sentences below.
- Do not add any finding, diagnosis, drug, dose or measurement that is not there.
- Do not infer or expand. If a detail is absent, leave it absent.
- Keep every number, dose and unit exactly as written.
- Write in the third person, in the style of a clinical note.
- Reply with the paragraph only, no preamble and no headings.

Sentences:
{bullets}

Paragraph:"""


class LLMSoapEngineError(Exception):
    """Raised when the LLM renderer is unavailable or fails."""


class LLMSoapEngine:
    _instance: Optional["LLMSoapEngine"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        if LLMSoapEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access LLMSoapEngine.")

        from app.core.config import settings

        self.model_id = getattr(settings, "LLM_MODEL_ID", "") or ""
        if not self.model_id:
            raise LLMSoapEngineError(
                "LLM_MODEL_ID is not set in .env. See app/ml/llm_soap_engine.py "
                "for the candidate models."
            )
        self.max_new_tokens = int(getattr(settings, "LLM_MAX_NEW_TOKENS", 220))

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as e:
            raise LLMSoapEngineError(
                f"Could not import transformers/torch ({type(e).__name__}: {e})."
            ) from e

        token = getattr(settings, "HF_TOKEN", "") or None
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, token=token)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                token=token,
                dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
            )
            self.model.eval()
        except Exception as e:
            raise LLMSoapEngineError(
                f"Failed to load {self.model_id} ({type(e).__name__}: {e})."
            ) from e

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            logger.warning(
                "LLMSoapEngine is running on CPU. Generation will be slow; the "
                "single-session latency budget is already missed at 36.5s."
            )
        logger.info("LLMSoapEngine loaded %s on %s", self.model_id, self.device)

    @classmethod
    def get_instance(cls) -> "LLMSoapEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------

    def render(self, sections: Dict[str, List[str]]) -> Dict[str, str]:
        from app.services.soap_service import FALLBACK_TEXT

        out: Dict[str, str] = {}
        for name in ("subjective", "objective", "assessment", "plan"):
            picked = [s.strip() for s in (sections.get(name) or []) if s.strip()]
            if not picked:
                out[name] = FALLBACK_TEXT
                continue
            try:
                out[name] = self._rewrite(name, picked)
            except Exception as e:
                # One section failing must not lose the note. Fall back to the
                # verbatim rendering for that section only, and say so in the
                # log so a degraded note is never mistaken for a generated one.
                logger.error(
                    "LLM rendering of %s failed (%s: %s); using verbatim text.",
                    name, type(e).__name__, e,
                )
                from app.services.soap_service import SOAPService
                out[name] = SOAPService.render_extractive({name: picked})[name]
        return out

    def _rewrite(self, section: str, sentences: List[str]) -> str:
        prompt = PROMPT.format(
            section=section.capitalize(),
            brief=SECTION_BRIEF[section],
            bullets="\n".join(f"- {s}" for s in sentences),
        )

        messages = [{"role": "user", "content": prompt}]
        if getattr(self.tokenizer, "chat_template", None):
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            text = prompt

        import torch
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        with _INFERENCE_LOCK, torch.no_grad():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,                     # greedy: reproducible
                pad_token_id=self.tokenizer.eos_token_id,
            )

        new_tokens = generated[0][inputs["input_ids"].shape[-1]:]
        answer = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        return self._clean(answer)

    @staticmethod
    def _clean(text: str) -> str:
        """
        Strip the scaffolding instruction-tuned models add anyway.

        Even with "reply with the paragraph only", models commonly return a
        markdown heading, a restated section name, or a lead-in such as
        "Here is the paragraph:". Removing it here keeps the groundedness
        metric measuring the clinical content rather than the boilerplate.
        """
        text = text.strip()
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        text = re.sub(r"^#+\s*.*?\n", "", text).strip()
        text = re.sub(
            r"^(here (is|are)[^:\n]*:|sure[^:\n]*:|paragraph:|"
            r"(subjective|objective|assessment|plan)\s*:)\s*",
            "", text, flags=re.IGNORECASE,
        ).strip()
        return " ".join(text.split())
