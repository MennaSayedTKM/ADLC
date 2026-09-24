"""add origin and suggestion_status to requirement_items, extend ai_calls call_type

Revision ID: f233c5463edb
Revises: 0a24adfddc28
Create Date: 2026-09-03 15:16:01.166976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f233c5463edb'
down_revision: Union[str, Sequence[str], None] = '0a24adfddc28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('requirement_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sa.String(), server_default='extracted', nullable=False))
        batch_op.add_column(sa.Column('suggestion_status', sa.String(), nullable=True))
        batch_op.create_check_constraint(
            'ck_requirement_items_origin',
            "origin in ('extracted','pm_manual','pm_ai_assisted','ai_suggestion')",
        )
        batch_op.create_check_constraint(
            'ck_requirement_items_suggestion_status',
            "suggestion_status is null or suggestion_status in ('pending','accepted','dismissed')",
        )

    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis','suggestions','item_draft')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis')",
        )

    with op.batch_alter_table('requirement_items', schema=None) as batch_op:
        batch_op.drop_constraint('ck_requirement_items_suggestion_status', type_='check')
        batch_op.drop_constraint('ck_requirement_items_origin', type_='check')
        batch_op.drop_column('suggestion_status')
        batch_op.drop_column('origin')
