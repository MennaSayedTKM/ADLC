"""alignment_reports.related_story_ids: the approved stories a design screen shows

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-18 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Null on reports from earlier checks: the link wasn't kept then."""
    with op.batch_alter_table('alignment_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('related_story_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('alignment_reports', schema=None) as batch_op:
        batch_op.drop_column('related_story_ids')
