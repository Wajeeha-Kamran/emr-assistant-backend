import logging
import numpy as np
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.code_reference import CodeReference
from app.ml.clinicalbert_engine import ClinicalBERTEngine

logger = logging.getLogger(__name__)

class CodeReferenceService:
    """
    Service responsible for loading reference codes from the database,
    caching their embeddings in memory, and performing semantic search.
    """
    _instance = None
    
    def __init__(self):
        if CodeReferenceService._instance is not None:
            raise RuntimeError("Use get_instance() to access CodeReferenceService.")
            
        self.codes: List[CodeReference] = []
        self.embeddings: List[np.ndarray] = []
        self._is_loaded = False

    @classmethod
    def get_instance(cls) -> "CodeReferenceService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self):
        """Loads codes from the DB and computes their embeddings if not already done."""
        if self._is_loaded:
            return
            
        logger.info("Loading code references and computing embeddings...")
        db: Session = SessionLocal()
        try:
            # Load all reference codes
            self.codes = db.query(CodeReference).all()
            
            if not self.codes:
                logger.warning("No code references found in database! Did you run the seed script?")
                self.embeddings = []
                self._is_loaded = True
                return
                
            # Extract descriptions for embedding
            descriptions = [code.description for code in self.codes]
            
            # Compute embeddings via ClinicalBERTEngine
            engine = ClinicalBERTEngine.get_instance()
            self.embeddings = engine.embed_batch(descriptions)
            
            self._is_loaded = True
            logger.info(f"Successfully loaded and embedded {len(self.codes)} reference codes.")
        finally:
            db.close()

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Standard NumPy cosine similarity (reused from clinicalbert_engine logic)."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def search_codes(self, text: str, top_k: int = 5) -> List[Tuple[CodeReference, float]]:
        """
        Search for the most semantically relevant codes for a given clinical text.
        Returns a list of tuples containing (CodeReference, similarity_score).
        """
        if not text.strip():
            return []
            
        self._ensure_loaded()
        
        if not self.codes:
            return []
            
        engine = ClinicalBERTEngine.get_instance()
        text_emb = engine.embed(text)
        
        # Calculate similarity against all cached code embeddings
        scored_codes = []
        for code, code_emb in zip(self.codes, self.embeddings):
            score = self._cosine_similarity(text_emb, code_emb)
            scored_codes.append((code, score))
            
        # Sort by similarity score descending
        scored_codes.sort(key=lambda x: x[1], reverse=True)
        
        return scored_codes[:top_k]
