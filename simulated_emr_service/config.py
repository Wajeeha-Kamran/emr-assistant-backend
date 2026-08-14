from pydantic_settings import BaseSettings, SettingsConfigDict

class SimulatedEMRSettings(BaseSettings):
    SIMULATED_EMR_DATABASE_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = SimulatedEMRSettings()
