"""
SIMULATED EMR SERVICE

This is a standalone Simulated EMR Service used strictly as a stand-in for a real EMR/EHR 
to demonstrate interoperability (UC-09, FR-07). 

IT MUST NOT BE TREATED AS PRODUCTION CODE.

This service receives finalized SOAP notes and acts as a mock downstream destination.
It connects to a completely separate database (`simulated_emr`) and should be run 
as a separate process.
"""

from fastapi import FastAPI
from simulated_emr_service.models import Base, engine
from simulated_emr_service.endpoints import router

# We use Base.metadata.create_all instead of Alembic migrations here because
# Alembic is scoped strictly to the main `emr_assistant` database. Since this is 
# a standalone simulated service backed by a different database, using create_all 
# is the correct and simplest approach to guarantee the table exists on startup.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Simulated EMR Service",
    description="A mock downstream EMR system for testing integration.",
    version="0.1.0"
)

app.include_router(router)
