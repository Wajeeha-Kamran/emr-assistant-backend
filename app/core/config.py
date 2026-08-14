from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "EMR Assistant Backend"
    APP_ENV: str  # Required setting to ensure config fails loudly if missing
    DATABASE_URL: str
    SIMULATED_EMR_URL: str
    
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    
    AUDIO_STORAGE_DIR: str = "./storage/audio"
    WHISPER_MODEL_NAME: str = "base.en"
    ASR_ENGINE: str = "whisper"          # Options: "whisper", "riva"
    DIARIZATION_PAUSE_THRESHOLD: float = 1.5
    
    # --- NFR Reconciliation: Robustness vs Efficiency ---
    # The 5-second Robustness requirement governs how quickly a FAILURE is reported 
    # to the caller. It is NOT a cap on how long successful processing may take 
    # (the Efficiency NFR allows 15s-25s for SOAP generation under load). 
    # Timeouts are runaway guards, sized above the performance budget.
    NLP_TIMEOUT_SECONDS: int = 30
    
    # ASR is slower than real-time on CPU, and supports 30-minute recordings. 
    # A fixed timeout would kill valid long transcriptions.
    # Timeout is computed dynamically: max(FLOOR, duration * FACTOR)
    ASR_TIMEOUT_FLOOR_SECONDS: int = 300
    ASR_TIMEOUT_FACTOR: int = 6

    # Retention: audio is held for RETENTION_WINDOW_MINUTES after being flagged,
    # then deleted on the next sweep. Worst-case latency = window + interval.
    # With defaults 4 min + 60 s = 5 min, satisfying the SRS's 5-minute NFR.
    RETENTION_WINDOW_MINUTES: int = 4
    RETENTION_SWEEP_INTERVAL_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
