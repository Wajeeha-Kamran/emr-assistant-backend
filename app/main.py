from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME
)

@app.get("/health")
def health_check():
    return {"status": "ok"}
