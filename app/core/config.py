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

    # Retention: audio is held for RETENTION_WINDOW_MINUTES after being flagged,
    # then deleted on the next sweep. Worst-case latency = window + interval.
    # With defaults 4 min + 60 s = 5 min, satisfying the SRS's 5-minute NFR.
    RETENTION_WINDOW_MINUTES: int = 4
    RETENTION_SWEEP_INTERVAL_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
