"""
Brings the TEST database's schema up to date.

The test database is NOT migration-managed. tests/conftest.py creates it and
calls Base.metadata.create_all, so it has no alembic_version row and Alembic
would try to replay the entire history onto a schema that already exists.

create_all has a blind spot: it only creates tables that are missing entirely.
A column or index added to a table that already exists is never applied, so the
test database silently falls behind the models. That failure is loud but
misleading — every test touching the table dies with UndefinedColumn, which
looks like broken code rather than a stale schema. It has now happened twice:
once for the generation_status columns, once for generation_started_at.

The previous version of this script closed the gap with a hand-written list of
ALTER statements. That list is the thing that fell behind — nobody remembers to
add to it, and there is no signal when they forget. This version derives the
difference from the models instead: it reflects what the database actually has,
compares it against Base.metadata, and adds whatever is missing. New columns are
picked up with no edit to this file.

The hand-written list survives only for the things reflection cannot derive from
a column definition: enum *values* added to an existing type, and the functional
unique index on lower(email).

Idempotent. Run it as often as you like.

sync_schema() is also called by tests/conftest.py after create_all, so an
ordinary `pytest` run repairs its own schema. Running this script by hand is
only needed if you want to see what changed, or to fix the database without
running the suite.

Usage, from the repository root:
    .\\.venv\\Scripts\\python.exe -m scripts.migrate_test_db
"""

import os
import sys
from urllib.parse import urlparse, urlunparse

import sqlalchemy as sa
from sqlalchemy import inspect, text


# ---------------------------------------------------------------------------
# The parts reflection cannot derive
# ---------------------------------------------------------------------------

# AUTOCOMMIT: ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
# older PostgreSQL. A value added to an existing enum is invisible to
# create_all, which only ever creates the type whole.
AUTOCOMMIT_STATEMENTS = [
    ("sessionstatus.DISCARDED",
     "ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'DISCARDED'"),
]

# Indexes and constraints that are not expressed as a plain column definition.
STATEMENTS = [
    ("ix_doctors_email_lower",
     "CREATE UNIQUE INDEX IF NOT EXISTS ix_doctors_email_lower ON doctors (lower(email))"),
]


def sync_missing_columns(engine, metadata) -> list[str]:
    """Add every column the models declare and the database lacks.

    Returns the labels of what was added, so a caller can report it.

    Tables that do not exist at all are skipped: create_all builds those
    correctly and will have run first.

    A NOT NULL column with no server_default is added NULL-able, because
    ALTER TABLE ADD COLUMN NOT NULL fails outright on a table with rows in it
    and stopping the whole run over that would be worse. The models fill these
    on insert via their Python-side default, so tests are unaffected; the
    difference is reported rather than hidden.
    """
    added: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        live = {col["name"] for col in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in live:
                continue

            label = f"{table.name}.{column.name}"

            # An enum column needs its type to exist before the column can
            # reference it. checkfirst makes this safe to repeat.
            if isinstance(column.type, sa.Enum):
                column.type.create(bind=engine, checkfirst=True)

            type_sql = column.type.compile(dialect=engine.dialect)
            ddl = (
                f'ALTER TABLE "{table.name}" '
                f'ADD COLUMN IF NOT EXISTS "{column.name}" {type_sql}'
            )

            if column.server_default is not None:
                # arg is either a SQL expression (text("now()")) or a plain
                # Python string. The string form has to be quoted or the DDL is
                # a syntax error — DEFAULT completed rather than
                # DEFAULT 'completed'.
                arg = column.server_default.arg
                default_sql = arg.text if hasattr(arg, "text") else f"'{arg}'"
                ddl += f" DEFAULT {default_sql}"
                if not column.nullable:
                    ddl += " NOT NULL"
            elif not column.nullable:
                label += "  (added NULL-able: NOT NULL in the model, no server_default)"

            with engine.connect() as conn:
                conn.execute(text(ddl))
                conn.commit()

            added.append(label)

    return added


def apply_extras(engine) -> None:
    """Enum values and indexes, which a column definition does not describe."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for _, sql in AUTOCOMMIT_STATEMENTS:
            conn.execute(text(sql))

    with engine.connect() as conn:
        for _, sql in STATEMENTS:
            conn.execute(text(sql))
            conn.commit()


def sync_schema(engine, metadata) -> list[str]:
    """Everything create_all cannot do to a database that already exists."""
    added = sync_missing_columns(engine, metadata)
    apply_extras(engine)
    return added


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main() -> None:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        from dotenv import dotenv_values
        raw = dotenv_values(".env").get("DATABASE_URL")
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
    from sqlalchemy import create_engine  # noqa: E402

    import app.db.base  # noqa: E402,F401
    from app.db.base import Base  # noqa: E402
    from app.models import (  # noqa: E402,F401
        audio, code_reference, code_suggestion, doctor, session as session_model,
        signature, soap_note, transcript,
    )

    engine = create_engine(target)

    # Missing tables first — a no-op on an existing database.
    Base.metadata.create_all(bind=engine)

    added = sync_schema(engine, Base.metadata)

    if added:
        for label in added:
            print(f"  added {label}")
    else:
        print("  no missing columns")

    for label, _ in AUTOCOMMIT_STATEMENTS + STATEMENTS:
        print(f"  {label}: ensured")

    engine.dispose()
    print("Test database schema is up to date.")


if __name__ == "__main__":
    main()
