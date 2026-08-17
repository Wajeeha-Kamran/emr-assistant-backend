"""Add the DISCARDED session state and discarded_at

Revision ID: c8d3e4f5a6b7
Revises: b7c1d2e3f4a5
Create Date: 2026-08-17

The mobile client creates a session and calls start-recording the moment the
doctor presses Start, so that the server genuinely observes UC-01 rather than
being told about it afterwards. That leaves one state the system could not
previously express: a consultation the doctor began and then abandoned before
any audio was uploaded.

Such a session would sit in RECORDING permanently. It is not reported by the
attention list, and correctly so — with no audio and no transcript there is
nothing to resume and nothing on disk to clean up — so nothing would ever close
it.

DISCARDED closes it, and discarded_at records when. The row is kept rather than
deleted: it holds no clinical content, but the fact that a consultation was
started and abandoned is itself something an audit would want to see.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # PostgreSQL, and on newer versions the new value cannot be used in the same
    # transaction that adds it. autocommit_block sidesteps both.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS 'DISCARDED'")

    op.add_column(
        "consultation_sessions",
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("consultation_sessions", "discarded_at")
    # The enum value is deliberately not removed. PostgreSQL cannot drop a value
    # from an enum type, and recreating the type would require rewriting every
    # row in the table. A spare value nothing writes is harmless.
