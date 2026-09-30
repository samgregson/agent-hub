"""Persist Batch Runs and their Result Records.

Revision ID: 0009_batch_runs
Revises: 0008_datasets_and_batch_definitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0009_batch_runs"
down_revision = "0008_datasets_and_batch_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch_runs",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("batch_run_id", sa.String(length=36), nullable=False),
        sa.Column("batch_definition_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "batch_run_id"),
    )
    op.create_table(
        "batch_result_records",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("batch_run_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_record_id", sa.String(length=36), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "batch_run_id"],
            ["batch_runs.project_id", "batch_runs.batch_run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "batch_run_id", "dataset_record_id"),
    )


def downgrade() -> None:
    op.drop_table("batch_result_records")
    op.drop_table("batch_runs")
