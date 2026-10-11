"""Store prepared Workflow Run snapshots.

Revision ID: 0025_workflow_runs
Revises: 0024_workflow_definitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0025_workflow_runs"
down_revision = "0024_workflow_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("initiator_subject", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "run_id"),
        sa.UniqueConstraint("project_id", "idempotency_key"),
        sa.CheckConstraint("definition_version > 0"),
    )


def downgrade() -> None:
    op.drop_table("workflow_runs")
