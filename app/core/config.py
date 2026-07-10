from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "EMR Assistant Backend"
    API_V1_STR: str = "/api/v1"
    
    # Placeholder fields from .env
    DATABASE_URL: str
    SIMULATED_EMR_DATABASE_URL: str
    JWT_SECRET: str
    REDIS_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
