"""ux_prompts: nullable epic_item_id (platform blueprint) and screens column

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ux_prompts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('screens', sa.JSON(), nullable=True))
        batch_op.alter_column('epic_item_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # A blueprint row has no epic, so it can't survive the NOT NULL restore.
    op.execute("DELETE FROM ux_prompts WHERE epic_item_id IS NULL")
    with op.batch_alter_table('ux_prompts', schema=None) as batch_op:
        batch_op.alter_column('epic_item_id', existing_type=sa.String(), nullable=False)
        batch_op.drop_column('screens')
