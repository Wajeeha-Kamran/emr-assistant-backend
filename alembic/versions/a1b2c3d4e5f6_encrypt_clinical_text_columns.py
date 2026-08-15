"""encrypt clinical text columns

Revision ID: a1b2c3d4e5f6
Revises: 68e4ed0603e3
Create Date: 2026-08-15 14:47:00.000000

Changes transcript_segments.text and soap_sections.content from
VARCHAR/TEXT to BYTEA so the EncryptedText TypeDecorator can store
Fernet ciphertext.  Both tables are confirmed empty (0 rows), so
USING NULL::bytea is safe — there is no data to transform.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'fba44024baa6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both tables are empty (verified before generating this migration).
    # USING NULL::bytea avoids the invalid text→bytea cast that PostgreSQL
    # would reject at statement-analysis time regardless of row count.
    op.execute(
        'ALTER TABLE transcript_segments '
        'ALTER COLUMN "text" TYPE bytea USING NULL::bytea'
    )
    op.execute(
        'ALTER TABLE soap_sections '
        'ALTER COLUMN content TYPE bytea USING NULL::bytea'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE transcript_segments '
        'ALTER COLUMN "text" TYPE varchar USING NULL::varchar'
    )
    op.execute(
        'ALTER TABLE soap_sections '
        'ALTER COLUMN content TYPE text USING NULL::text'
    )
