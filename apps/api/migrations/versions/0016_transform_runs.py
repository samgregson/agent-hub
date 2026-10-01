"""Retain Project-owned Transform Run snapshots and terminal outcomes.

Revision ID: 0016_transform_runs
Revises: 0015_transform_definitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0016_transform_runs"
down_revision = "0015_transform_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transform_runs",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("transform_run_id", sa.String(length=36), nullable=False),
        sa.Column("transform_definition_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("runtime", sa.String(length=120), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("output_manifest", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=120), nullable=True),
        sa.Column("initiator_subject", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "transform_run_id"),
    )
    op.create_index(
        "ix_transform_runs_definition_created",
        "transform_runs",
        ["project_id", "transform_definition_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_transform_runs_definition_created", table_name="transform_runs")
    op.drop_table("transform_runs")
