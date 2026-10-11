"""Store Project Workflow Definitions.

Revision ID: 0024_workflow_definitions
Revises: 0023_file_bindings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0024_workflow_definitions"
down_revision = "0023_file_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "workflow_id"),
        sa.CheckConstraint("version > 0"),
    )


def downgrade() -> None:
    op.drop_table("workflow_definitions")
