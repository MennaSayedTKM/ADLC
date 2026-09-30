"""add ux_prompts, projects.style_brief; extend ai_calls.call_type with 'ux_prompt'

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding')"
)
_AFTER = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding','ux_prompt')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('style_brief', sa.JSON(), nullable=True))

    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _AFTER)

    op.create_table(
        'ux_prompts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('epic_item_id', sa.String(), nullable=False),
        sa.Column('story_ids', sa.JSON(), nullable=False),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('style_brief', sa.JSON(), nullable=True),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('edited_text', sa.Text(), nullable=True),
        sa.Column('is_stale', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "mode in ('foundation','new_feature','edit_existing')", name='ck_ux_prompts_mode'
        ),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['epic_item_id'], ['requirement_items.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ux_prompts')

    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _BEFORE)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('style_brief')
