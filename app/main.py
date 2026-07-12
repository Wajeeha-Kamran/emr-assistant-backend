from fastapi import FastAPI
from app.core.config import settings
from app.core.logging import setup_logging

from app.api.v1.endpoints import auth

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
