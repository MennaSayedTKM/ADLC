"""add evaluation_reports; extend ai_calls call_type

Revision ID: 22ad0821a349
Revises: c3d4e5f6a7b8
Create Date: 2026-09-16 14:15:06.744780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22ad0821a349'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'evaluation_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('input_quality_score', sa.Integer(), nullable=False),
        sa.Column('output_quality_score', sa.Integer(), nullable=False),
        sa.Column('input_summary', sa.Text(), nullable=False),
        sa.Column('output_summary', sa.Text(), nullable=False),
        sa.Column('key_findings', sa.JSON(), nullable=False),
        sa.Column('recommendations', sa.JSON(), nullable=False),
        sa.Column('signals', sa.JSON(), nullable=False),
        sa.Column('weak_story_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('input_quality_score between 0 and 100', name='ck_evaluation_reports_input_score'),
        sa.CheckConstraint('output_quality_score between 0 and 100', name='ck_evaluation_reports_output_score'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', name='uq_evaluation_reports_document_id'),
    )
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions',"
            "'policy_coverage','source_material_review','output_story_review',"
            "'artifact_quality_review')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions',"
            "'policy_coverage')",
        )
    op.drop_table('evaluation_reports')
