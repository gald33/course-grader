"""Rename presentation/rubric stage value 'initial' -> 'presentation'

The course originally distinguished an "initial" and a "final" talk per
project. In practice only one talk happens, so the 'initial' identifier is
renamed to 'presentation' across the three tables that store its data:
presentation_scores.stage, rubric_dimension_scores.component, and
student_component_overrides.component. The 'final' value is left alone — it
remains as plumbing while no longer contributing to the grade formula.

Revision ID: 0008_rename_initial_stage_to_presentation
Revises: 0007_code_review_json
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_rename_initial_stage_to_presentation"
down_revision: Union[str, None] = "0007_code_review_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE presentation_scores SET stage = 'presentation' WHERE stage = 'initial'")
    op.execute("UPDATE rubric_dimension_scores SET component = 'presentation' WHERE component = 'initial_talk'")
    op.execute("UPDATE student_component_overrides SET component = 'presentation' WHERE component = 'initial_talk'")


def downgrade() -> None:
    op.execute("UPDATE student_component_overrides SET component = 'initial_talk' WHERE component = 'presentation'")
    op.execute("UPDATE rubric_dimension_scores SET component = 'initial_talk' WHERE component = 'presentation'")
    op.execute("UPDATE presentation_scores SET stage = 'initial' WHERE stage = 'presentation'")
