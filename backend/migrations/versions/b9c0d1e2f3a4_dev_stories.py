"""development stories: dev_stories, dev_tasks, jira_epics; projects.tech_profile and
projects.jira_settings; extend ai_calls.call_type for the development module

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-10-14 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding','ux_prompt','use_case_diagram')"
)
_AFTER = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding','ux_prompt','use_case_diagram',"
    "'dev_story','coding_prompt','screen_match','tech_profile')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tech_profile', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('jira_settings', sa.JSON(), nullable=True))

    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _AFTER)

    op.create_table(
        'dev_stories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('epic_item_id', sa.String(), nullable=False),
        sa.Column('source_story_item_id', sa.String(), nullable=True),
        sa.Column('epic_external_id', sa.String(), nullable=False),
        sa.Column('source_story_external_id', sa.String(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('acceptance_criteria', sa.JSON(), nullable=False),
        sa.Column('story_points', sa.Integer(), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=False),
        sa.Column('jira_key', sa.String(), nullable=True),
        sa.Column('jira_url', sa.String(), nullable=True),
        sa.Column('jira_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['epic_item_id'], ['requirement_items.id']),
        sa.ForeignKeyConstraint(['source_story_item_id'], ['requirement_items.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'dev_tasks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dev_story_id', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('area', sa.String(), nullable=False),
        sa.Column('coding_prompt', sa.Text(), nullable=True),
        sa.Column('edited_prompt', sa.Text(), nullable=True),
        sa.Column('tech_decision_needed', sa.Boolean(), nullable=False),
        sa.Column('decision_areas', sa.JSON(), nullable=False),
        sa.Column('prompt_generated_at', sa.DateTime(), nullable=True),
        sa.Column('screens', sa.JSON(), nullable=False),
        sa.Column('jira_key', sa.String(), nullable=True),
        sa.Column('jira_url', sa.String(), nullable=True),
        sa.Column('jira_synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['dev_story_id'], ['dev_stories.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'jira_epics',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('epic_external_id', sa.String(), nullable=False),
        sa.Column('jira_key', sa.String(), nullable=False),
        sa.Column('jira_url', sa.String(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'epic_external_id', name='uq_jira_epics_project_epic'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('jira_epics')
    op.drop_table('dev_tasks')
    op.drop_table('dev_stories')

    op.execute(
        "DELETE FROM ai_calls WHERE call_type IN ('dev_story','coding_prompt','screen_match','tech_profile')"
    )
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _BEFORE)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('jira_settings')
        batch_op.drop_column('tech_profile')
