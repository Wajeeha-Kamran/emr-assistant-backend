from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Index, String, DateTime, text
from datetime import datetime, timezone
from app.db.base import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # The email is this system's account identifier, so it has to be unique
    # without regard to capitalisation. The plain unique index above is
    # case-sensitive, as PostgreSQL indexes are, which allowed
    # "Doctor@clinic.com" and "doctor@clinic.com" to exist as two accounts for
    # one person — with the consultations recorded under each invisible from
    # the other.
    #
    # Declared on the model rather than only in the migration so that both ways
    # of building the schema produce it: Alembic for the development database,
    # and Base.metadata.create_all for the test database, which is not
    # migration-managed.
    __table_args__ = (
        Index("ix_doctors_email_lower", text("lower(email)"), unique=True),
    )
