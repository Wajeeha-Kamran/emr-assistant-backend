"""add_generation_status_to_soap_notes

Revision ID: 244389e99126
Revises: c8d3e4f5a6b7
Create Date: 2026-08-20 10:06:21.883377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '244389e99126'
down_revision: Union[str, Sequence[str], None] = 'c8d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    generation_status_enum = sa.Enum('processing', 'completed', 'failed', name='generationstatus')
    generation_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('soap_notes', sa.Column('generation_status', generation_status_enum, nullable=False, server_default='completed'))
    op.add_column('soap_notes', sa.Column('generation_error', sa.String(), nullable=True))
    op.add_column('soap_notes', sa.Column('codes_generation_status', generation_status_enum, nullable=True))
    op.add_column('soap_notes', sa.Column('codes_generation_error', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('soap_notes', 'codes_generation_error')
    op.drop_column('soap_notes', 'codes_generation_status')
    op.drop_column('soap_notes', 'generation_error')
    op.drop_column('soap_notes', 'generation_status')
    
    generation_status_enum = sa.Enum('processing', 'completed', 'failed', name='generationstatus')
    generation_status_enum.drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###
