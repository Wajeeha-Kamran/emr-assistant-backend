import logging
import torch
from transformers import BioGptTokenizer, BioGptForCausalLM

logger = logging.getLogger(__name__)

from app.ml.clinicalbert_engine import SOAPGenerationError

class BioGPTEngine:
    _instance = None

    def __init__(self) -> None:
        if BioGPTEngine._instance is not None:
            raise RuntimeError("Use get_instance() to access BioGPTEngine.")
        
        # Check for GPU (cuda), fallback to CPU
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Initializing BioGPTEngine using device: {self.device}")
        
        # Load the tokenizer and model once
        try:
            # We explicitly accept the Bandit B615 risk of unpinned models here.
            # Pinning revisions with HuggingFace transformers reliably triggers
            # background API calls to check for safetensors conversions on unmerged PRs,
            # which breaks our security/network isolation requirements.
            self.tokenizer = BioGptTokenizer.from_pretrained(
                "microsoft/biogpt"  # nosec B615
            )
            self.model = BioGptForCausalLM.from_pretrained(
                "microsoft/biogpt"  # nosec B615
            ).to(self.device)
        except Exception as e:
            raise SOAPGenerationError(f"Failed to load BioGPT model: {e}") from e

    @classmethod
    def get_instance(cls) -> "BioGPTEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate(self, prompt: str, max_new_tokens: int = 250) -> str:
        """
        Generates text using the BioGPT model based on the prompt.
        Raises SOAPGenerationError if generation fails.
        """
        try:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,  # Greedy decoding for consistent clinical structure
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode the generated tokens (only the newly generated ones)
            input_length = inputs.input_ids.shape[1]
            generated_text = self.tokenizer.decode(outputs[0][input_length:], skip_special_tokens=True)
            return generated_text
            
        except Exception as e:
            raise SOAPGenerationError(f"BioGPT text generation failed: {e}") from e
