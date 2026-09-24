"""add evaluation_reports per-category scores

Revision ID: 7a5f4552b91a
Revises: 22ad0821a349
Create Date: 2026-09-16 15:19:51.853754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a5f4552b91a'
down_revision: Union[str, Sequence[str], None] = '22ad0821a349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('evaluation_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_material_score', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('stories_score', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('advisory_content_score', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_check_constraint(
            'ck_evaluation_reports_source_score', 'source_material_score between 0 and 100'
        )
        batch_op.create_check_constraint('ck_evaluation_reports_stories_score', 'stories_score between 0 and 100')
        batch_op.create_check_constraint(
            'ck_evaluation_reports_advisory_score', 'advisory_content_score between 0 and 100'
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('evaluation_reports', schema=None) as batch_op:
        batch_op.drop_constraint('ck_evaluation_reports_advisory_score', type_='check')
        batch_op.drop_constraint('ck_evaluation_reports_stories_score', type_='check')
        batch_op.drop_constraint('ck_evaluation_reports_source_score', type_='check')
        batch_op.drop_column('advisory_content_score')
        batch_op.drop_column('stories_score')
        batch_op.drop_column('source_material_score')
