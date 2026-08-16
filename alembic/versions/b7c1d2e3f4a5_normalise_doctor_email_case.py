"""Normalise doctor emails to lowercase and enforce case-insensitive uniqueness

Revision ID: b7c1d2e3f4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-08-16

The doctors table had a unique index on email, but PostgreSQL unique indexes
are case-sensitive. Combined with an exact-match duplicate check at
registration, "Doctor@clinic.com" and "doctor@clinic.com" were two separate
accounts for one person.

That is not cosmetic here. Every session, transcript and note is scoped by
doctor_id, and the attention list is the only way to reach an unfinished
consultation. A doctor who signed in with different capitalisation would be
looking at an empty account, unable to see or sign work recorded under the
other one — and its audio, which is deleted only after a successful sync, would
never be cleaned up.

This migration lowercases the existing rows and adds a unique index on
lower(email), so the database refuses the duplicate rather than relying on the
application to remember to check.

The original unique index on email is deliberately kept. Once every row is
lowercase the two are equivalent, and leaving it means no existing query loses
its index.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_doctors_email_lower"


def upgrade() -> None:
    bind = op.get_bind()

    # Refuse to guess. If two accounts already differ only by case, this
    # migration cannot decide which one owns the consultations recorded under
    # the other, and silently merging or dropping either would destroy clinical
    # records. Report them and stop.
    collisions = bind.execute(sa.text("""
        SELECT lower(btrim(email)) AS normalised,
               count(*)            AS accounts,
               string_agg(id::text || ':' || email, ', ' ORDER BY id) AS rows
        FROM doctors
        GROUP BY 1
        HAVING count(*) > 1
    """)).fetchall()

    if collisions:
        detail = " | ".join(f"{row.normalised} -> {row.rows}" for row in collisions)
        raise RuntimeError(
            "Cannot normalise doctor emails: these accounts differ only by "
            "capitalisation, so lowercasing them would violate the unique "
            "constraint.\n\n"
            f"  {detail}\n\n"
            "Decide which account is the real one, move or delete the other "
            "(check consultation_sessions.doctor_id first), then re-run this "
            "migration."
        )

    bind.execute(sa.text("""
        UPDATE doctors
        SET email = lower(btrim(email))
        WHERE email <> lower(btrim(email))
    """))

    # Raw DDL rather than op.create_index: this is a functional index, and
    # expression support in create_index varies between Alembic versions.
    op.execute(f"CREATE UNIQUE INDEX {INDEX_NAME} ON doctors (lower(email))")


def downgrade() -> None:
    # The index can be removed. The lowercasing cannot be undone — the original
    # capitalisation was not recorded anywhere, and inventing one would be
    # worse than leaving the addresses normalised.
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
