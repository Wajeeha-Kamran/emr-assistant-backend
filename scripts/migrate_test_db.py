"""
Brings the TEST database's schema up to date.

The test database is NOT migration-managed. tests/conftest.py creates it and
calls Base.metadata.create_all, so it has no alembic_version row and Alembic
would try to replay the entire history onto a schema that already exists.

create_all also has a blind spot: it only creates tables that are missing
entirely. An index added to an existing table — such as the case-insensitive
unique index on doctors.email — is never applied to a test database that was
built before the index was declared. The tests would then pass locally while
the constraint they rely on does not exist.

This script closes that gap. It is idempotent: run it as often as you like.

Usage, from the repository root:
    .\\.venv\\Scripts\\python.exe -m scripts.migrate_test_db
"""

import os
import sys
from urllib.parse import urlparse, urlunparse

from dotenv import dotenv_values

raw = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
if not raw:
    sys.exit("FATAL: DATABASE_URL is not set in the environment or in .env.")

parsed = urlparse(raw)
name = parsed.path.lstrip("/")
if not name.endswith("_test"):
    parsed = parsed._replace(path=f"/{name}_test")

target = urlunparse(parsed)
target_name = urlparse(target).path.lstrip("/")

if not target_name.endswith("_test"):
    sys.exit(f"REFUSING TO RUN: '{target_name}' is not a test database.")

os.environ["DATABASE_URL"] = target
print(f"Target database: {target_name}")

# Imported only after the override, so the engine binds to the test database.
from sqlalchemy import create_engine, text  # noqa: E402

import app.db.base  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402,F401
    audio, code_reference, code_suggestion, doctor, session as session_model,
    signature, soap_note, transcript,
)

engine = create_engine(target)

# Missing tables first — this is a no-op on an existing database.
Base.metadata.create_all(bind=engine)

# Then the objects create_all will not add to a table that already exists:
# columns and enum values on tables it has already seen. Every statement is
# written to be safe to re-run.
#
# AUTOCOMMIT for the enum: ALTER TYPE ... ADD VALUE cannot run inside a
# transaction block on older PostgreSQL.
AUTOCOMMIT_STATEMENTS = [
    ("sessionstatus.DISCARDED",
     "ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'DISCARDED'"),
]

STATEMENTS = [
    ("ix_doctors_email_lower",
     "CREATE UNIQUE INDEX IF NOT EXISTS ix_doctors_email_lower ON doctors (lower(email))"),
    ("consultation_sessions.discarded_at",
     "ALTER TABLE consultation_sessions ADD COLUMN IF NOT EXISTS discarded_at TIMESTAMPTZ"),
]

with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
    for label, sql in AUTOCOMMIT_STATEMENTS:
        conn.execute(text(sql))
        print(f"  {label}: ensured")

with engine.connect() as conn:
    for label, sql in STATEMENTS:
        conn.execute(text(sql))
        conn.commit()
        print(f"  {label}: ensured")

engine.dispose()
print("Test database schema is up to date.")
