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

# Bumped whenever the prompt text changes, because a prompt change invalidates
# every previous score. v1 results are not comparable with v2 results.
#
# v1 -> v2 (10 Sep 2026): added the prohibition on unstated negatives.
#   Under v1, MedGemma 4B wrote "The patient denies any other symptoms" and
#   Mistral 7B wrote "The patient denies any history of fractures or
#   dislocations" -- both in script 2's Subjective, both with zero overlap
#   against anything in the consultation. Two unrelated model families
#   producing the same class of fabrication in the same place is a property of
#   the instruction, not of either model: "write a clinical paragraph" invites
#   clinical-note convention, and pertinent negatives are convention. v1
#   forbade adding findings but never said that "no X" and "denies X" are
#   themselves findings.
PROMPT_VERSION = "v2"

PROMPT = """You are helping a doctor write the {section} section of a SOAP note.

The {section} section records {brief}.

Below are the sentences already selected for this section, taken verbatim from
a consultation recording. Rewrite them as one short, clinical paragraph.

Rules:
- Use ONLY the information in the sentences below.
- Do not add any finding, diagnosis, drug, dose or measurement that is not there.
- Do not infer or expand. If a detail is absent, leave it absent.
- Do not state that anything was denied, normal, absent, unremarkable or not
  present unless the sentences below say so. An absence is a clinical finding
  and inventing one is the same as inventing a symptom.
- Keep every number, dose and unit exactly as written.
- Write in the third person, in the style of a clinical note.
- Reply with the paragraph only, no preamble and no headings.

Sentences:
{bullets}

Paragraph:"""


def _compute_dtype(preference: str = "auto"):
    """
    Pick the load precision. NEVER float16.

    MEASURED 11 Sep 2026: loading Gemma in float16 makes its logits NaN, so
    argmax returns token 0 and the model emits nothing but padding. MedGemma
    scored 0.0% on its first run for exactly this reason, and the failure reads
    like the model being bad at the task rather than a numerical fault. The
    Colab notebook was fixed at the time; this engine was not, because nothing
    had ever run it.

    bfloat16 has the same exponent range as float32, so it does not overflow
    the way float16 does, and it halves memory against float32 — which matters
    on CPU, where a 4B model is about 16 GB in float32 and 8 GB in bfloat16.

    Override with LLM_DTYPE = auto | bfloat16 | float32.
    """
    import torch

    choice = (preference or "auto").strip().lower()
    if choice == "bfloat16":
        return torch.bfloat16
    if choice == "float32":
        return torch.float32
    if choice not in ("", "auto"):
        logger.warning("Unknown LLM_DTYPE %r; using auto.", preference)

    if torch.cuda.is_available():
        supported = getattr(torch.cuda, "is_bf16_supported", lambda: False)()
        return torch.bfloat16 if supported else torch.float32
    return torch.bfloat16


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
        self.gate_enabled = bool(getattr(settings, "LLM_GROUNDING_GATE", True))
        from app.ml.grounding import DEFAULT_THRESHOLD
        self.gate_threshold = float(
            getattr(settings, "LLM_GROUNDING_THRESHOLD", DEFAULT_THRESHOLD))

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as e:
            raise LLMSoapEngineError(
                f"Could not import transformers/torch ({type(e).__name__}: {e})."
            ) from e

        token = getattr(settings, "HF_TOKEN", "") or None
        dtype = _compute_dtype(getattr(settings, "LLM_DTYPE", "auto"))
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, token=token)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                token=token,
                dtype=dtype,
                device_map="auto" if torch.cuda.is_available() else None,
            )
            self.model.eval()
        except Exception as e:
            raise LLMSoapEngineError(
                f"Failed to load {self.model_id} ({type(e).__name__}: {e})."
            ) from e

        self.dtype = dtype
        self._assert_healthy()

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cpu":
            logger.warning(
                "LLMSoapEngine is running on CPU. Generation will be slow; the "
                "single-session latency budget is already missed at 36.5s."
            )
        logger.info("LLMSoapEngine loaded %s on %s", self.model_id, self.device)

    def _assert_healthy(self) -> None:
        """
        Generate a few tokens and refuse to start if they are degenerate.

        A model loaded at the wrong precision does not crash. It emits padding,
        and every downstream metric reports it as a very bad model. That is how
        MedGemma came to be recorded at 0.0% clinical accuracy on 11 Sep 2026
        before the cause was found. A load-time check turns a silent wrong
        answer into a loud failure, which the fallback chain then handles by
        using the extractive renderer.
        """
        import torch

        probe = "Rewrite this as one sentence: the patient reports a headache."
        try:
            inputs = self.tokenizer(probe, return_tensors="pt").to(self.model.device)
            with _INFERENCE_LOCK, torch.no_grad():
                out = self.model.generate(
                    **inputs,
                    max_new_tokens=8,
                    do_sample=False,
                    pad_token_id=self.tokenizer.eos_token_id,
                )
        except Exception as e:
            raise LLMSoapEngineError(
                f"{self.model_id} failed its load-time health check "
                f"({type(e).__name__}: {e})."
            ) from e

        new_tokens = out[0][inputs["input_ids"].shape[-1]:]
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        if not text:
            raise LLMSoapEngineError(
                f"{self.model_id} produced only padding at dtype {self.dtype}. "
                "This is the float16 NaN fault, not a bad model. Set "
                "LLM_DTYPE=float32 and retry."
            )
        logger.info("LLMSoapEngine health check passed (%s, %s): %r",
                    self.model_id, self.dtype, text[:60])

    @classmethod
    def get_instance(cls) -> "LLMSoapEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------

    def render(self, sections: Dict[str, List[str]]) -> Dict[str, str]:
        from app.services.soap_service import fallback_for

        out: Dict[str, str] = {}
        for name in ("subjective", "objective", "assessment", "plan"):
            picked = [s.strip() for s in (sections.get(name) or []) if s.strip()]
            if not picked:
                out[name] = fallback_for(name)
                continue
            try:
                text = self._rewrite(name, picked)
                out[name] = self._gate(name, picked, text)
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

    def _gate(self, section: str, sentences: List[str], text: str) -> str:
        """
        Apply the grounding gate, unless it has been switched off.

        The decision itself lives in app/ml/grounding.gate_section, because
        the remote renderer needs exactly the same check and a gate that
        exists in only one of two renderers is not a gate. See the comment
        above that function.

        LLM_GROUNDING_GATE=false is a real off switch, used to measure what
        the model produces without it. Nothing else should turn it off.
        """
        if not getattr(self, "gate_enabled", True):
            return text

        from app.ml.grounding import gate_section
        return gate_section(section, sentences, text, self.gate_threshold)

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
