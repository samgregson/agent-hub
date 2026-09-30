"""Retain archived Batch Runs and their Result Sets.

Revision ID: 0013_archive_batch_runs
Revises: 0012_batch_run_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0013_archive_batch_runs"
down_revision = "0012_batch_run_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_runs", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.drop_constraint("fk_batch_runs_definition", "batch_runs", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "fk_batch_runs_definition",
        "batch_runs",
        "batch_definitions",
        ["project_id", "batch_definition_id"],
        ["project_id", "batch_definition_id"],
        ondelete="CASCADE",
    )
    op.drop_column("batch_runs", "archived_at")
