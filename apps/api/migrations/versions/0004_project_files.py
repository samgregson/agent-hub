"""Create project-scoped virtual files.

Revision ID: 0004_project_files
Revises: 0003_run_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_project_files"
down_revision: str | None = "0003_run_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("path", sa.String(length=1024), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_files")
