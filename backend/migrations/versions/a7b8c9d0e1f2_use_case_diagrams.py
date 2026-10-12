"""add use_case_diagrams; extend ai_calls.call_type with 'use_case_diagram'

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding','ux_prompt')"
)
_AFTER = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding','ux_prompt','use_case_diagram')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'use_case_diagrams',
        sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('plantuml', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('content_hash'),
    )
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _AFTER)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM ai_calls WHERE call_type = 'use_case_diagram'")
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _BEFORE)
    op.drop_table('use_case_diagrams')
