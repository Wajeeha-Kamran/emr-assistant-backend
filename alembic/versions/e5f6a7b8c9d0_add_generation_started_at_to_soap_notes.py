"""add_generation_started_at_to_soap_notes

Stall detection previously measured its deadline from soap_notes.created_at.
That is the moment the note row was created, not the moment a background job
started, and the two diverge in normal use:

  * Code suggestion is triggered after the doctor has read the draft. Any review
    longer than NLP_TIMEOUT_SECONDS + ATTENTION_STALL_BUFFER_SECONDS meant the
    job was reported CODES_GENERATION_STALLED the instant it began.
  * A retry reuses the existing note, so created_at stays old. is_soap_stalled
    returned True immediately, which defeated the 409 guard on the retry
    endpoint and allowed concurrent background tasks on one note.

These two columns record when each job actually started. Both are nullable:
rows written before this migration have no start time, and AttentionService
falls back to created_at for them, which is the behaviour they were built with.

Revision ID: e5f6a7b8c9d0
Revises: 244389e99126
Create Date: 2026-08-20 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = '244389e99126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'soap_notes',
        sa.Column('generation_started_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'soap_notes',
        sa.Column('codes_generation_started_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('soap_notes', 'codes_generation_started_at')
    op.drop_column('soap_notes', 'generation_started_at')
