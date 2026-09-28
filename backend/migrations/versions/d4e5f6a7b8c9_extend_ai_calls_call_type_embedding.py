"""extend ai_calls.call_type with 'embedding' (Cohere Embed v4 on Bedrock)

Revision ID: d4e5f6a7b8c9
Revises: 7a5f4552b91a
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '7a5f4552b91a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review')"
)
_AFTER = (
    "call_type in ('extraction','alignment','rerank','crop','synthesis',"
    "'suggestions','item_draft','intake_transcription','clarifying_questions',"
    "'policy_coverage','source_material_review','output_story_review',"
    "'artifact_quality_review','embedding')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _AFTER)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_calls', schema=None) as batch_op:
        batch_op.drop_constraint('ck_ai_calls_call_type', type_='check')
        batch_op.create_check_constraint('ck_ai_calls_call_type', _BEFORE)
