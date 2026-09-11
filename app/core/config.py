from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "EMR Assistant Backend"
    APP_ENV: str  # Required setting to ensure config fails loudly if missing
    DATABASE_URL: str
    SIMULATED_EMR_URL: str
    
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    
    # Encryption key for clinical text columns (Fernet, base64-encoded 32 bytes).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str
    
    AUDIO_STORAGE_DIR: str = "./storage/audio"
    WHISPER_MODEL_NAME: str = "base.en"
    ASR_ENGINE: str = "whisper"          # Options: "whisper", "riva"
    # --- Diarization ---
    # "embedding" = voice fingerprints clustered into two speakers (default).
    # "pause"     = DEPRECATED original heuristic. Measured 15 Aug 2026: it
    #               never fires, because Whisper leaves no gaps between
    #               segments (93 gaps, mean 0.006s, max 0.560s). Retained only
    #               for the design-evolution record.
    # "sortformer" = NeMo end-to-end diarization (default). 99.9% speaker
    #                accuracy on the four scripted consultations; needs no
    #                Hugging Face token. Requires: pip install nemo_toolkit[asr]
    # "pyannote"   = purpose-built pipeline, kept as the automatic fallback.
    #                77.6% on the same recordings — it swaps both speakers on
    #                script 2. See docs/evidence/benchmarks/diarizer_head_to_head.csv
    # "window" / "embedding" / "pause" = earlier attempts, retained for
    # the design-evolution record. See DiarizationService for measurements.
    DIARIZATION_METHOD: str = "sortformer"

    # Hugging Face read token, required only by the pyannote fallback.
    # Licences must be accepted for pyannote/segmentation-3.0,
    # pyannote/speaker-diarization-3.1 and
    # pyannote/speaker-diarization-community-1 on huggingface.co.
    HF_TOKEN: str = ""
    DIARIZATION_PAUSE_THRESHOLD: float = 1.5  # only used by the deprecated method
    
    # --- NFR Reconciliation: Robustness vs Efficiency ---
    # The 5-second Robustness requirement governs how quickly a FAILURE is reported 
    # to the caller. It is NOT a cap on how long successful processing may take 
    # (the Efficiency NFR allows 15s-25s for SOAP generation under load). 
    # Timeouts are runaway guards, sized above the performance budget.
    # --- SOAP rendering engine ---
    # "extractive" = join the selected sentences verbatim (default). Novel
    #                content rate 0.0% by construction: nothing can be invented.
    # "llm"        = an instruction-tuned model rewrites the SAME selected
    #                sentences as prose. It never sees the raw transcript.
    #                Requires LLM_MODEL_ID. Measure with
    #                scripts/evaluate_groundedness.py BEFORE adopting one --
    #                BioGPT already failed this project by ignoring its
    #                instruction and completing text instead.
    SOAP_ENGINE: str = "extractive"
    LLM_MODEL_ID: str = ""
    LLM_MAX_NEW_TOKENS: int = 220

    # Reject any generated sentence the transcript does not support, and fall
    # back to the verbatim rendering for that section. On by default: under
    # prompt v2, which explicitly forbids it, MedGemma 4B and Mistral 7B each
    # still invented a pertinent negative the patient never gave. See
    # app/ml/grounding.py.
    LLM_GROUNDING_GATE: bool = True
    LLM_GROUNDING_THRESHOLD: float = 0.5

    NLP_TIMEOUT_SECONDS: int = 30
    
    # ASR is slower than real-time on CPU, and supports 30-minute recordings. 
    # A fixed timeout would kill valid long transcriptions.
    # Timeout is computed dynamically: max(FLOOR, duration * FACTOR)
    ASR_TIMEOUT_FLOOR_SECONDS: int = 300
    ASR_TIMEOUT_FACTOR: int = 6

    # Retention: audio is held for RETENTION_WINDOW_MINUTES after being flagged,
    # then deleted on the next sweep. Worst-case latency = window + interval.
    # With defaults 4 min + 60 s = 5 min, satisfying the SRS's 5-minute NFR.
    # Attention list: an unfinished consultation is only reported as stuck once
    # it is older than this. The window exists so work in progress does not
    # appear in its own author's attention list. Sized well above a normal
    # consultation so it cannot fire mid-consultation.
    ATTENTION_GRACE_MINUTES: int = 30

    # Added to the ASR time budget before a transcript still in `processing` is
    # treated as abandoned. Covers the commit that follows a timeout, so a job
    # finishing right on its deadline is not reported as stalled.
    ATTENTION_STALL_BUFFER_SECONDS: int = 120

    RETENTION_WINDOW_MINUTES: int = 4
    RETENTION_SWEEP_INTERVAL_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# --- Fail loudly at startup if ENCRYPTION_KEY is missing or malformed ---
# Constructing Fernet here validates the key format (must be 32 url-safe
# base64-encoded bytes).  An absent or placeholder key stops the app
# immediately with a clear error, rather than surfacing later inside a
# request handler or background task.  This also satisfies Module 10.3.
from cryptography.fernet import Fernet
try:
    Fernet(settings.ENCRYPTION_KEY.encode())
except Exception as e:
    raise SystemExit(
        f"FATAL: ENCRYPTION_KEY is missing or malformed. "
        f"Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
        f"Error: {e}"
    )
