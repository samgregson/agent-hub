"""Create Threads and Agent Runs.

Revision ID: 0002_threads_and_runs
Revises: 0001_projects
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_threads_and_runs"
down_revision: str | None = "0001_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_threads_project_updated",
        "threads",
        ["project_id", "updated_at"],
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(length=36),
            sa.ForeignKey("threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_agent_runs_thread_updated",
        "agent_runs",
        ["thread_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_thread_updated", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_threads_project_updated", table_name="threads")
    op.drop_table("threads")
