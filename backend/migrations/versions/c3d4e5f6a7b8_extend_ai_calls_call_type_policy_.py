"""extend ai_calls.call_type with 'policy_coverage'

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions',"
            "'policy_coverage')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions')",
        )
