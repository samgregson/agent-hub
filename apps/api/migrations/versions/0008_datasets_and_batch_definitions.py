"""Persist Project-owned Datasets and Batch Definitions.

Revision ID: 0008_datasets_and_batch_definitions
Revises: 0007_artifact_user_action_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0008_datasets_and_batch_definitions"
down_revision = "0007_artifact_user_action_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "dataset_id"),
    )
    op.create_table(
        "dataset_records",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=240), nullable=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "dataset_id"],
            ["datasets.project_id", "datasets.dataset_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "dataset_id", "record_id"),
        sa.UniqueConstraint("project_id", "dataset_id", "position"),
    )
    op.create_table(
        "batch_definitions",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("batch_definition_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("plugin_id", sa.String(length=120), nullable=False),
        sa.Column("tool_name", sa.String(length=240), nullable=False),
        sa.Column("argument_mappings", sa.JSON(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "batch_definition_id"),
    )


def downgrade() -> None:
    op.drop_table("batch_definitions")
    op.drop_table("dataset_records")
    op.drop_table("datasets")
