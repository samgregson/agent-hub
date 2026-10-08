"""Persist Project File Bindings for MCP Batch Definitions.

Revision ID: 0023_file_bindings
Revises: 0022_file_binding_argument
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0023_file_bindings"
down_revision = "0022_file_binding_argument"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_bindings",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("batch_definition_id", sa.String(length=36), nullable=False),
        sa.Column("argument", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("expected_file_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "binding_id"),
        sa.UniqueConstraint("project_id", "batch_definition_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "batch_definition_id"],
            ["batch_definitions.project_id", "batch_definitions.batch_definition_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("expected_file_version > 0"),
    )


def downgrade() -> None:
    op.drop_table("file_bindings")
