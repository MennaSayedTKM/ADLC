"""add intake_resources, clarifying_questions, standing_policies; relax ai_calls.document_id, add ai_calls.project_id, extend call_type

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.String(), nullable=True))
        batch_op.alter_column('document_id', existing_type=sa.String(), nullable=True)
        batch_op.create_foreign_key('fk_ai_calls_project_id', 'projects', ['project_id'], ['id'])
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft','intake_transcription','clarifying_questions')",
        )

    op.create_table(
        'intake_resources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('resource_kind', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('processing_error', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "resource_kind in ('primary_requirements','meeting_notes','policy_reference','other')",
            name='ck_intake_resources_resource_kind',
        ),
        sa.CheckConstraint("file_type in ('pdf','docx','image')", name='ck_intake_resources_file_type'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'clarifying_questions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('topic_area', sa.String(), nullable=True),
        sa.Column('why_it_matters', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status in ('pending','answered','skipped')", name='ck_clarifying_questions_status'
        ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'standing_policies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('policy_text', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('standing_policies')
    op.drop_table('clarifying_questions')
    op.drop_table('intake_resources')

    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint(
            'ck_ai_calls_call_type',
            "call_type in ('extraction','alignment','rerank','crop','synthesis',"
            "'suggestions','item_draft')",
        )
        batch_op.drop_constraint('fk_ai_calls_project_id', type_='foreignkey')
        batch_op.alter_column('document_id', existing_type=sa.String(), nullable=False)
        batch_op.drop_column('project_id')
