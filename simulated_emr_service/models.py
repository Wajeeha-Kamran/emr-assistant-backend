from sqlalchemy import create_engine, Integer, JSON, DateTime
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone
from simulated_emr_service.config import settings

engine = create_engine(
    settings.SIMULATED_EMR_DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class SimulatedEMRRecord(Base):
    __tablename__ = "simulated_emr_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_session_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_soap_note_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Using a callable lambda ensures a distinct timestamp on every insert rather than import time
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
